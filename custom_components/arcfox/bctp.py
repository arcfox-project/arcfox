"""BCTP/MQTT envelope helpers for ARCFOX remote control commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ArcfoxVehicle
from .protocol import ArcfoxCommandPayload, ArcfoxCommandSpec


@dataclass(frozen=True, slots=True)
class BctpHeader:
    """Header fields observed in the ARCFOX BCTP control entity."""

    ver: int = 1
    group: int = 10
    cmd: int = 0
    token: str = ""
    st: int = 0
    seq: int = 1
    down: int = 0
    up: int = 0

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
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable BCTP envelope."""
        envelope: dict[str, Any] = {"cmddown": {"header": self.header.to_dict(), "body": self.payload}}
        if self.business_code is not None:
            envelope["businessCode"] = self.business_code
        return envelope


@dataclass(frozen=True, slots=True)
class BctpPublishRequest:
    """Fully materialized BCTP publish request."""

    topic: str
    envelope: BctpCommandEnvelope
    qos: int = 0
    retain: bool = False

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


def build_command_envelope(
    *,
    action: str,
    spec: ArcfoxCommandSpec,
    payload: ArcfoxCommandPayload | None,
    token: str,
    seq: int = 1,
    st: int = 0,
    business_code: str | None = None,
) -> BctpCommandEnvelope:
    """Create a BCTP command envelope from a high-level action."""
    command_payload = payload.to_dict() if payload is not None else {}
    command_payload["action"] = action
    command_payload["command"] = spec.command
    if spec.notes:
        command_payload["notes"] = spec.notes
    header = BctpHeader(
        group=spec.group or (payload.group if payload is not None else 10),
        cmd=spec.cmd or (payload.cmd if payload is not None else 0),
        token=token,
        st=st,
        seq=seq,
    )
    return BctpCommandEnvelope(business_code=business_code, header=header, payload=command_payload)


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
    st: int = 0,
    business_code: str | None = None,
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
    envelope = build_command_envelope(
        action=action,
        spec=spec,
        payload=payload,
        token=token,
        seq=seq,
        st=st,
        business_code=business_code,
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
    )
