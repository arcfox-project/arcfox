"""BCTP/MQTT envelope helpers for ARCFOX remote control commands.

Frame layout is reconstructed from the decompiled ``BctpParseUtilsKt``
(``composeBctpAgreement`` / ``decomposeBctpAgreement``) and the business payload
is the ``ElectircVehiRmtCtrlControlBuf`` protobuf whose single ``cmddown``
field carries the JSON-serialized ``BctpControlCmdEntity``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from .cmac import cmac_string
from .models import ArcfoxVehicle
from .protocol import ArcfoxCommandPayload, ArcfoxCommandSpec

# Device number observed in every BCTP frame built by the SDK.
DEVICE_NUMBER = 3123

# Protocol name is 0 for the regular frame and 103 for the N80KS/B31CS
# variant which additionally carries a 30-byte terminal barcode.
PROTOCOL_NAME_DEFAULT = 0
PROTOCOL_NAME_TERMINAL_BARCODE = 103

# The SDK increments two independent counters: ``messageNumber`` (frame header)
# and ``CommandUtils.seq`` (JSON header SEQ). Both start small and are only used
# as correlation IDs, so a single module-level counter is sufficient.
_seq = 0


def _next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def _st_string(now: datetime) -> str:
    """Return the SDK's ``TimeUtils.getTimeMill`` ST format."""
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _bctp_date_bytes(now: datetime) -> bytes:
    """Encode the 10-byte send-time field.

    Mirrors ``BctpParseUtilsKt.toByteDateFromLongTime``::
        [0, year_hi, year_lo, month, day, hour, minute, second, millis_hi, millis_lo]
    """
    data = bytearray(10)
    data[0] = 0
    data[1:3] = now.year.to_bytes(2, "big")
    data[3] = now.month
    data[4] = now.day
    data[5] = now.hour
    data[6] = now.minute
    data[7] = now.second
    data[8:10] = (now.microsecond // 1000).to_bytes(2, "big")
    return bytes(data)


@dataclass(frozen=True, slots=True)
class BctpHeader:
    """JSON header of ``BctpControlCmdEntity.HeaderEntity``.

    All fields are strings because the entity is Gson-serialized into the
    protobuf ``cmddown`` payload. ``DOWN`` is ``"1"`` by default and the SDK
    sets it to ``"2"`` for a small set of command strings.
    """

    ver: str = "1"
    group: str = "10"
    cmd: str = "0"
    token: str = ""
    st: str = ""
    seq: str = "1"
    down: str = "1"
    up: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable header representation."""
        return {
            "VER": self.ver,
            "GROUP": self.group,
            "CMD": self.cmd,
            "TOKEN": self.token,
            "ST": self.st,
            "SEQ": self.seq,
            "DOWN": self.down,
            "UP": self.up,
        }


@dataclass(frozen=True, slots=True)
class BctpCommandEnvelope:
    """Transport envelope that wraps a remote control command."""

    business_code: str | None
    header: BctpHeader
    body: dict[str, Any]
    cyber: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable BCTP envelope for logging."""
        envelope: dict[str, Any] = {
            "cmddown": {
                "header": self.header.to_dict(),
                "body": self.body,
            }
        }
        if self.cyber is not None:
            envelope["cmddown"]["cyber"] = self.cyber
        if self.business_code is not None:
            envelope["businessCode"] = self.business_code
        return envelope

    def to_inner_json(self) -> bytes:
        """Encode the protobuf field-1 JSON payload used by the App."""
        value: dict[str, Any] = {
            "header": self.header.to_dict(),
            "body": self.body,
        }
        if self.cyber is not None:
            value["cyber"] = self.cyber
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def to_protobuf(self) -> bytes:
        """Encode ``ElectircVehiRmtCtrlControl.cmddown`` (field 1 string)."""
        value = self.to_inner_json()
        length = len(value)
        prefix = bytearray([0x0A])
        while length > 0x7F:
            prefix.append((length & 0x7F) | 0x80)
            length >>= 7
        prefix.append(length)
        return bytes(prefix) + value

    def to_bctp_frame(self, vin: str, *, protocol_name: int = PROTOCOL_NAME_DEFAULT) -> bytes:
        """Build the binary BCTP frame used on MQTT topic/21."""
        if len(vin.encode("ascii")) != 17:
            raise ValueError("ARCFOX BCTP VIN must be exactly 17 ASCII bytes")
        body = self.to_protobuf()
        business_code = (self.business_code or "1000")[:4]
        try:
            type_bytes = bytes.fromhex(business_code)
        except ValueError as err:
            raise ValueError(f"Invalid BCTP business code: {business_code}") from err
        if len(type_bytes) != 2:
            raise ValueError("BCTP business code must encode exactly two bytes")

        now = datetime.now()
        frame = bytearray()
        frame.append(protocol_name)
        frame.append(1)
        frame.extend(vin.encode("ascii"))
        if protocol_name == PROTOCOL_NAME_TERMINAL_BARCODE:
            frame.extend(b"0" * 30)
        frame.extend(DEVICE_NUMBER.to_bytes(4, "big"))
        frame.extend(type_bytes)
        frame.append(0)
        frame.extend(_bctp_date_bytes(now))
        frame.append(2)
        frame.extend((_next_seq() & 0xFFFF).to_bytes(2, "big"))
        frame.extend((1).to_bytes(2, "big"))
        frame.extend(len(body).to_bytes(4, "big"))
        frame.extend(body)
        return bytes(frame)


@dataclass(frozen=True, slots=True)
class BctpPublishRequest:
    """Fully materialized BCTP publish request."""

    topic: str
    envelope: BctpCommandEnvelope
    qos: int = 0
    retain: bool = False
    vin: str = ""

    def payload_bytes(self) -> bytes:
        """Return the actual MQTT payload, not the diagnostic JSON view."""
        return self.envelope.to_bctp_frame(self.vin)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for logging or transport."""
        data = self.envelope.to_dict()
        data["topic"] = self.topic
        data["qos"] = self.qos
        data["retain"] = self.retain
        return data


def build_terminal_topic(
    vin: str,
    *,
    channel: str = "bctp",
    product: str = "N5",
    scope: str = "standard",
    target: str = "terminal",
    suffix: str = "topic/21",
) -> str:
    """Build a terminal topic using the observed ARCFOX topic layout."""
    return f"{channel}/{product}/{scope}/{target}/{vin}/{suffix}"


def _infer_topic_route(
    vehicle: ArcfoxVehicle | str,
    *,
    default_channel: str = "bctp",
    default_product: str = "N5",
) -> tuple[str, str]:
    """Infer the most likely channel/product pair from the vehicle model."""
    if not isinstance(vehicle, ArcfoxVehicle):
        return default_channel, default_product

    model = (vehicle.model or "").strip().upper()
    route_map: dict[str, tuple[str, str]] = {
        "BE12": ("bctp", "BE12"),
        "N5": ("bctp", "N5"),
        "N50AB": ("bctp", "N5"),
        "N51AB": ("bctp", "N5"),
        "N50AS": ("bctp", "N5"),
        "N51AS": ("bctp", "N5"),
        "N53TB": ("bctp", "N53TB"),
        "C37TB": ("bctp", "C37TB"),
        "C66TB": ("bctp", "C66TB"),
        "C66TS": ("bctp", "C66TS"),
        "C66TB_Z04": ("bctp", "C66TB-Z04"),
        "C12HB": ("bctp", "C12HB"),
        "N80KS": ("bctp2", "N80KS"),
        "B31CS": ("bctp2", "B31CS"),
        "N60": ("bctp2", "N60AS"),
    }
    return route_map.get(model, (default_channel, model or default_product))


def compute_cyber(
    *,
    rc_key_hex: str,
    user_id: str,
    header: BctpHeader,
    body: dict[str, Any],
    cloud_cks: bool,
) -> dict[str, Any] | None:
    """Compute the ``cyber`` object for CMAC-enabled vehicle models.

    The SDK signs ``Gson().toJson(BctpControlCmdEntity)`` with AES-CMAC using
    the per-vehicle ``rcKey`` as the key. ``keyID`` is ``"00"`` when the key is
    a cloud CKS and ``"01"`` otherwise. Returns ``None`` when the rcKey is not a
    valid AES key.
    """
    message = json.dumps(
        {"header": header.to_dict(), "body": body},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    cmac = cmac_string(rc_key_hex, message)
    if cmac is None:
        return None
    return {
        "userID": user_id,
        "keyID": "00" if cloud_cks else "01",
        "CMAC": cmac,
    }


def build_command_envelope(
    *,
    action: str,
    spec: ArcfoxCommandSpec,
    payload: ArcfoxCommandPayload | None,
    token: str,
    seq: int = 1,
    st: str = "",
    business_code: str | None = None,
    cyber: dict[str, Any] | None = None,
) -> BctpCommandEnvelope:
    """Create a BCTP command envelope from a high-level action."""
    group = spec.group if spec.group is not None else (payload.group if payload is not None else 10)
    cmd = spec.cmd if spec.cmd is not None else (payload.cmd if payload is not None else 0)

    body: dict[str, Any] = {}
    if payload is not None:
        # The RemoteRequestBean body keeps ``c`` and ``p1..p12``; ``group`` and
        # ``cmd`` are nulled and carried by the uppercase header fields instead.
        for key, value in payload.to_dict().items():
            if key not in {"group", "cmd"} and value is not None:
                body[key] = str(value)

    header = BctpHeader(
        group=str(group),
        cmd=str(cmd),
        token=token,
        st=st,
        seq=str(seq),
    )
    return BctpCommandEnvelope(
        business_code=business_code,
        header=header,
        body=body,
        cyber=cyber,
    )


def envelope_to_payload_dict(envelope: BctpCommandEnvelope) -> dict[str, Any]:
    """Flatten an envelope into a dictionary suitable for logging or publishing."""
    return envelope.to_dict()


def build_publish_request(
    vehicle: ArcfoxVehicle | str,
    *,
    action: str,
    spec: ArcfoxCommandSpec,
    payload: ArcfoxCommandPayload | None,
    token: str,
    seq: int = 1,
    st: str = "",
    business_code: str | None = None,
    cyber: dict[str, Any] | None = None,
    topic_channel: str = "bctp",
    topic_product: str = "N5",
    topic_scope: str = "standard",
    topic_target: str = "terminal",
    topic_suffix: str = "topic/21",
) -> BctpPublishRequest:
    """Create a publish request for an ARCFOX terminal command."""
    vin = vehicle.vin if isinstance(vehicle, ArcfoxVehicle) else str(vehicle)
    inferred_channel, inferred_product = _infer_topic_route(
        vehicle,
        default_channel=topic_channel,
        default_product=topic_product,
    )
    if business_code is None and spec.cmd is not None:
        business_code = f"10{spec.cmd:02d}"
    envelope = build_command_envelope(
        action=action,
        spec=spec,
        payload=payload,
        token=token,
        seq=seq,
        st=st,
        business_code=business_code,
        cyber=cyber,
    )
    return BctpPublishRequest(
        topic=build_terminal_topic(
            vin,
            channel=inferred_channel,
            product=inferred_product,
            scope=topic_scope,
            target=topic_target,
            suffix=topic_suffix,
        ),
        envelope=envelope,
        qos=1,
        vin=vin,
    )
