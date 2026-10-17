"""Read-only ARCFOX In-Vehicle network (IOV) TCP client.

Implements the 60115/60015 TCP protocol used by the ARCFOX app to talk to
the vehicle control gateway.  Only passive/read-only operations are exposed:

* online status query
* full vehicle state query (battery, mileage, doors, locks, tire pressure,
  location, temperatures, charge state, ...)

No control commands (locks, windows, horn, lights, find-car, climate, ...)
are implemented here.

The protocol was reverse-engineered from the official ARCFOX Android app and
is documented in the repository notes.  Credentials are supplied by the
caller and never persisted by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import struct
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

DEFAULT_HOST = "arcfoxapp-new-iov.bjev.com.cn"
DEFAULT_PORT = 60115
DEFAULT_APP_ID = "ae9db49b-7b8e-411d-ae16-e227a782b7af"
DEFAULT_APP_KEY = "2368392532"
DEFAULT_SECRET_KEY = "26abfc143bfe3cda422d91e4c9ca4783"
TOKEN_ENDPOINT_PATH = "vehicle-customer/public/vehicle/getVehicleToken"
TOKEN_ENDPOINT_BASE = "https://mg.arcfox.cn/"

FIXED_KEY = b"1234567812345678"
FIXED_IV = b"1234567812345678"

# request-side message IDs (data.c.a.C0016a)
MSG_ONLINE_QUERY = -32759
MSG_FULL_STATE_QUERY = -32511  # DRIVE_CAR_DATA
# response-side message IDs (data.c.a.c)
MSG_ONLINE_RESP = 6
MSG_FULL_STATE_RESP = 4098  # CarDataResponse

# queryItems keys sent by order.e.a(); all values are empty strings.
QUERY_ITEM_KEYS = (
    "INSTANTANEOUS_ENERGY",
    "SUBTOTAL_ENERGY",
    "ISHIDE",
    "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9",
    "S10", "S11", "S12", "S13", "S14", "S15", "S16", "S17", "S18", "S19",
    "S20", "S21", "S22", "S23", "S24", "S25", "S26", "S27", "S28",
    "S30", "S31", "S32", "S33", "S34", "S35", "S36", "S37", "S38", "S39",
    "S40", "S41", "S42", "S43", "S44", "S45", "S46", "S47", "S48", "S49",
    "S50", "S51", "S52", "S53", "S54",
    "S56", "S57", "S58", "S59", "S60", "S61", "S62", "S63", "S64", "S65",
    "S66", "S67",
    "S70", "S71", "S72", "S73", "S74",
    "S89", "S90", "S91", "S92", "S93", "S94", "S95", "S96", "S97", "S98",
    "S99", "S100", "S101", "S102",
    "S110", "S111", "S112", "S113", "S114", "S115", "S116", "S117", "S118",
    "S119", "S120",
)

# Field-name mapping extracted from com.intest.valley.control.sdk.order.e.c().
S_FIELD_MAP: dict[str, str] = {
    "S1": "charge_state",
    "S2": "climate_state",
    "S3": "defrost_state",
    "S4": "lock_state",
    "S5": "charge_power_kw",
    "S6": "window_state",
    "S7": "sunroof_state",
    "S8": "charge_voltage_v",
    "S9": "charge_push_state",
    "S10": "battery_heat_state",
    "S11": "lamp_delay_state",
    "S12": "seat_occupancy_state",
    "S13": "lock_peps_state",
    "S14": "foot_trunk_state",
    "S15": "drive_temperature",
    "S16": "charge_appointment",
    "S17": "climate_appointment",
    "S18": "defrost_appointment",
    "S19": "seat_heat_appointment",
    "S20": "seat_vent_appointment",
    "S21": "battery_heat_appointment",
    "S22": "charge_gun_state",
    "S23": "wireless_charge_reason",
    "S24": "current_battery",
    "S25": "charge_remaining_time",
    "S26": "charge_energy_kwh",
    "S27": "charging_guidance",
    "S28": "battery_temperature",
    "S30": "charge_stop_reason",
    "S31": "target_soc",
    "S32": "battery_preserve_state",
    "S33": "charge_preserve_state",
    "S34": "long_heat_state",
    "S35": "range_km",
    "S36": "location",
    "S37": "charge_relevant_reason",
    "S38": "electronic_lock_abnormal",
    "S39": "trunk_state",
    "S40": "total_mileage",
    "S41": "front_machine_state",
    "S42": "left_front_door",
    "S43": "left_back_door",
    "S44": "right_back_door",
    "S45": "user_machine",
    "S46": "right_front_door",
    "S47": "charge_end_soc",
    "S48": "air_temperature",
    "S49": "right_front_seat_heat",
    "S50": "right_front_seat_vent",
    "S51": "left_front_seat_heat",
    "S52": "left_front_seat_vent",
    "S53": "discharge_state",
    "S54": "lamp_delay_time",
    "S56": "tire_left_front",
    "S57": "tire_right_front",
    "S58": "tire_left_rear",
    "S59": "tire_right_rear",
    "S60": "charge_energy_show",
    "S61": "left_back_seat_heat",
    "S62": "right_back_seat_heat",
    "S63": "charge_appointment_state",
    "S64": "vehicle_alignment_state",
    "S65": "charge_gun_dc_state",
    "S66": "range_display_type",
    "S67": "gear_wakeup_signal",
    "S70": "weak_current_state",
    "S71": "steering_wheel_state",
    "S72": "steering_wheel_appointment",
    "S73": "fast_charge_port",
    "S74": "slow_charge_port",
    "S89": "storage_wakeup_cycle",
    "S90": "storage_monitor_msg",
    "S91": "charge_status_prompt",
    "S92": "smart_charge_mode",
    "S93": "custom_mode",
    "S94": "remote_function_mode",
    "S95": "healthy_storage_user_status",
    "S96": "healthy_storage_request",
    "S97": "soc_planning",
    "S98": "charge_discharge_request",
    "S99": "ventilation_state",
    "S100": "ventilation_appointment",
    "S101": "window_close",
    "S102": "ready_indicator",
    "S110": "vital_sign_alarm_off",
    "S111": "vital_sign_alarm_off_ac",
    "S112": "sentinel_mode_status",
    "S113": "sentinel_mode_value",
    "S114": "filter_life_switch",
    "S115": "filter_life",
    "S116": "filter_life_expiration",
    "S117": "sentry_mode_state",
    "S118": "remote_view_status",
    "S119": "perspective_state",
    "S120": "video_clarity",
}


class ArcfoxIovError(Exception):
    """Base error for the IOv client."""


class ArcfoxIovAuthError(ArcfoxIovError):
    """Authentication or credential error."""


def _aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(out) + unpadder.finalize()


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def _pb_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _pb_bytes(field: int, data: bytes) -> bytes:
    return _pb_varint(field << 3 | 2) + _pb_varint(len(data)) + data


def _pb_string(field: int, value: str) -> bytes:
    return _pb_bytes(field, value.encode("utf-8"))


def _parse_proto(data: bytes) -> dict[int, list[tuple[int, Any]]]:
    fields: dict[int, list[tuple[int, Any]]] = {}
    offset = 0
    while offset < len(data):
        tag = 0
        shift = 0
        while True:
            byte = data[offset]
            offset += 1
            tag |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        field_number = tag >> 3
        wire_type = tag & 7
        if wire_type == 0:
            value = 0
            shift = 0
            while True:
                byte = data[offset]
                offset += 1
                value |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            fields.setdefault(field_number, []).append((wire_type, value))
        elif wire_type == 2:
            length = 0
            shift = 0
            while True:
                byte = data[offset]
                offset += 1
                length |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            value = data[offset:offset + length]
            offset += length
            fields.setdefault(field_number, []).append((wire_type, value))
        else:
            raise ArcfoxIovError(f"unsupported protobuf wire type {wire_type}")
    return fields


def _proto_varint_field(fields: dict, number: int, default: int = 0) -> int:
    values = fields.get(number)
    return values[0][1] if values else default


def _proto_bytes_field(fields: dict, number: int) -> bytes:
    values = fields.get(number)
    return values[0][1] if values else b""


def _split_location(value: Any) -> tuple[float | None, float | None]:
    """Parse 'lng;lat' location strings into (latitude, longitude)."""
    if value in (None, ""):
        return None, None
    if not isinstance(value, str):
        return None, None
    parts = value.split(";")
    if len(parts) != 2:
        return None, None
    try:
        longitude = float(parts[0].strip())
        latitude = float(parts[1].strip())
    except ValueError:
        return None, None
    return latitude, longitude


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in {"", "[]"}:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool_state(value: Any) -> bool | None:
    """Map a numeric/string state to a boolean (None when unknown)."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value not in (0,)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "off", "close", "closed", "unlocked", "idle", "no", "false"}:
            return False
        if normalized in {"1", "on", "open", "opened", "locked", "active", "yes", "true", "charging", "plugged"}:
            return True
    return None


def map_query_result(query_result: dict[str, Any]) -> dict[str, Any]:
    """Convert the raw S* queryResult into named, HA-friendly fields."""
    named: dict[str, Any] = {}
    for key, value in query_result.items():
        if not isinstance(key, str):
            continue
        named[S_FIELD_MAP.get(key, key)] = value

    for wheel, key in (
        ("left_front", "S56"),
        ("right_front", "S57"),
        ("left_rear", "S58"),
        ("right_rear", "S59"),
    ):
        raw = query_result.get(key)
        if isinstance(raw, str):
            try:
                wheel_data = json.loads(raw)
            except (TypeError, ValueError):
                wheel_data = None
            if isinstance(wheel_data, dict):
                named[f"tire_{wheel}_pressure_kpa"] = _coerce_float(
                    wheel_data.get("TPV")
                )

    latitude, longitude = _split_location(query_result.get("S36"))
    named["latitude"] = latitude
    named["longitude"] = longitude

    # Conservative boolean derivations for the most useful HA states.
    # S1 (chargeState) is cached and ambiguous across generations, so the
    # instantaneous charge/discharge power S5 (kW) is the authoritative
    # charging signal.
    charge_power = _coerce_float(query_result.get("S5"))
    named["is_charging"] = charge_power is not None and charge_power > 0.05
    # S22 is the charge gun state and S65 the DC charge gun state.
    named["is_plugged_in"] = _coerce_bool_state(
        query_result.get("S22") if query_result.get("S22") not in ("", None)
        else query_result.get("S65")
    )
    # S4 (lockState) uses 0 for locked and 1 for unlocked on the BE12 platform.
    lock_raw = query_result.get("S4")
    named["is_locked"] = (
        lock_raw == "0" if lock_raw not in (None, "") else None
    )
    named["climate_on"] = _coerce_bool_state(query_result.get("S2"))
    named["window_open"] = _coerce_bool_state(query_result.get("S6"))
    named["sunroof_open"] = _coerce_bool_state(query_result.get("S7"))
    named["trunk_open"] = _coerce_bool_state(query_result.get("S39"))
    return named


def _build_query_items() -> dict[str, str]:
    return {key: "" for key in QUERY_ITEM_KEYS}


def _make_query_token(vin: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    sequence = int(now.microsecond // 1000) % 10000
    return (
        "NZ"
        + vin[-6:]
        + now.strftime("%y%m%d%H%M%S")
        + f"{sequence:04d}"
    )


def _sign_token_request(path: str, params: dict[str, Any], secret: str) -> str:
    ordered = "".join(f"{key}={value}_" for key, value in sorted(params.items()))
    raw = f"{path}_{ordered}{secret}"
    encoded = urllib.parse.quote(raw, safe="")
    return hashlib.md5(encoded.encode("utf-8")).hexdigest().lower()


def fetch_remote_token(
    access_token: str,
    vin: str,
    *,
    app_key: str = DEFAULT_APP_KEY,
    secret_key: str = DEFAULT_SECRET_KEY,
    aid: str = "",
    imei: str = "",
    timeout: float = 15.0,
) -> str:
    """Exchange the app access token for a short-lived remote control token."""
    params = {
        "appkey": app_key,
        "signt": str(int(time.time() * 1000)),
        "nonce": str(uuid.uuid4()),
        "vin": vin,
        "token": access_token,
    }
    params["sign"] = _sign_token_request(TOKEN_ENDPOINT_PATH, params, secret_key)

    url = TOKEN_ENDPOINT_BASE + TOKEN_ENDPOINT_PATH + "?" + urllib.parse.urlencode(params)
    headers = {
        "User-Agent": "okhttp/4.9.1",
        "platform": "Android",
        "appversion": "3.4.28",
        "appcode": "325",
        "vin": vin,
    }
    if aid:
        headers["aid"] = aid
    if imei:
        headers["deviceId"] = imei

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        raise ArcfoxIovAuthError(f"getVehicleToken HTTP {err.code}") from err
    except urllib.error.URLError as err:
        raise ArcfoxIovError(f"getVehicleToken request failed: {err}") from err

    try:
        payload = json.loads(body)
    except ValueError as err:
        raise ArcfoxIovError("getVehicleToken returned invalid JSON") from err

    if payload.get("status") != "SUCCEED" or not payload.get("data"):
        raise ArcfoxIovAuthError(f"getVehicleToken failed: {payload}")

    return str(payload["data"])


class ArcfoxIovClient:
    """Blocking TCP client for read-only ARCFOX vehicle queries."""

    def __init__(
        self,
        vin: str,
        access_token: str,
        *,
        aid: str = "",
        imei: str = "",
        remote_token: str = "",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        app_key: str = DEFAULT_APP_KEY,
        secret_key: str = DEFAULT_SECRET_KEY,
        timeout: float = 15.0,
    ) -> None:
        if not vin:
            raise ArcfoxIovError("vin is required")
        if not access_token:
            raise ArcfoxIovAuthError("access_token is required")
        self.vin = vin
        self.access_token = access_token
        self.aid = aid
        self.imei = imei
        self._remote_token_override = (remote_token or "").strip()
        self.host = host
        self.port = port
        self.app_key = app_key
        self.secret_key = secret_key
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._session_key: bytes | None = None
        self._session_iv: bytes | None = None
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0x7FFF
        return self._sequence

    def _credentials(self, remote_token: str) -> bytes:
        vin = self.vin.encode("ascii", "ignore")[:17].ljust(17, b"\x00")
        try:
            aid = struct.pack("<Q", int(self.aid) & 0xFFFFFFFFFFFFFFFF)
        except (TypeError, ValueError):
            aid = struct.pack("<Q", 0)
        token = remote_token.encode("ascii", "ignore")[:32].ljust(32, b"\x00")
        return vin + aid + token

    def _build_frame(
        self,
        msg_type: int,
        body_msg_type: int,
        payload: bytes,
        remote_token: str,
    ) -> bytes:
        imei = self.imei.encode("ascii", "ignore")[:15].ljust(15, b"0")
        header = (
            bytes([msg_type, 8, 2])
            + imei
            + struct.pack("<H", self._next_sequence())
            + struct.pack("<h", body_msg_type)
            + struct.pack("<I", len(payload))
        )
        return header + payload + self._credentials(remote_token)

    def _recv_exact(self, length: int) -> bytes:
        if self._socket is None:
            raise ArcfoxIovError("not connected")
        buffer = bytearray()
        while len(buffer) < length:
            chunk = self._socket.recv(length - len(buffer))
            if not chunk:
                raise ArcfoxIovError("connection closed by server")
            buffer.extend(chunk)
        return bytes(buffer)

    def _recv_frame(self, deadline: float | None = None) -> tuple[int, int, bytes]:
        if self._socket is None:
            raise ArcfoxIovError("not connected")
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ArcfoxIovError("timeout waiting for server frame")
            self._socket.settimeout(min(self.timeout, remaining))
        try:
            head = self._recv_exact(26)
            msg_type = head[0]
            body_msg_type = struct.unpack("<h", head[20:22])[0]
            body_length = struct.unpack("<I", head[22:26])[0]
            body = self._recv_exact(body_length)
        except ArcfoxIovError:
            raise
        except OSError as err:
            raise ArcfoxIovError(f"socket error while reading server frame: {err}") from err
        return msg_type, body_msg_type, body

    def connect(self) -> None:
        """Fetch a remote token and complete the TCP handshake."""
        if self._remote_token_override:
            remote_token = self._remote_token_override
        else:
            remote_token = fetch_remote_token(
                self.access_token,
                self.vin,
                app_key=self.app_key,
                secret_key=self.secret_key,
                aid=self.aid,
                imei=self.imei,
                timeout=self.timeout,
            )
        self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._socket.settimeout(self.timeout)
        self._remote_token = remote_token

        client_random = os.urandom(16)
        client_id = self._next_sequence()
        client_hello = (
            _pb_varint(1 << 3) + _pb_varint(client_id)
            + _pb_bytes(2, client_random)
            + _pb_bytes(3, self._client_hello_signature(client_id, client_random))
            + _pb_string(4, DEFAULT_APP_ID)
        )
        self._socket.sendall(
            self._build_frame(1, 1, client_hello, remote_token)
        )

        server_id = 0
        server_random = b""
        hello_deadline = time.monotonic() + self.timeout
        for _ in range(10):
            msg_type, body_type, body = self._recv_frame(hello_deadline)
            if msg_type == 1 and body_type == 2:
                fields = _parse_proto(body)
                result = _proto_varint_field(fields, 2)
                if result != 0:
                    raise ArcfoxIovAuthError(f"ServerHello result={result}")
                server_id = _proto_varint_field(fields, 3)
                server_random = _proto_bytes_field(fields, 4)
                break

        self._session_key, self._session_iv, client_finish = self._client_finish(
            server_id, client_random, server_random
        )
        self._socket.sendall(
            self._build_frame(1, 3, client_finish, remote_token)
        )

        finish_deadline = time.monotonic() + self.timeout
        for _ in range(10):
            msg_type, body_type, body = self._recv_frame(finish_deadline)
            if msg_type == 1 and body_type == 4:
                fields = _parse_proto(body)
                if _proto_varint_field(fields, 2) != 0:
                    raise ArcfoxIovAuthError("ServerFinish failed")
                return

        raise ArcfoxIovError("handshake did not complete")

    @staticmethod
    def _client_hello_signature(client_id: int, client_random: bytes) -> bytes:
        pre = b"\x01\x00" + struct.pack("<H", client_id) + client_random
        return _aes_cbc_encrypt(FIXED_KEY, FIXED_IV, _sha256(pre))

    def _client_finish(
        self, server_id: int, client_random: bytes, server_random: bytes
    ) -> tuple[bytes, bytes, bytes]:
        def xor(left: bytes, right: bytes) -> bytes:
            return bytes(a ^ b for a, b in zip(left, right))

        key = _md5(xor(FIXED_KEY, client_random) + _md5(xor(FIXED_KEY, server_random)))
        iv = _md5(client_random + FIXED_IV + server_random)
        client_id = self._next_sequence()
        pre = b"\x03\x00" + struct.pack("<H", server_id) + b"\x00" + struct.pack("<H", client_id)
        signature = _aes_cbc_encrypt(key, iv, _sha256(pre))
        proto = (
            _pb_varint(1 << 3) + _pb_varint(client_id)
            + _pb_varint(2 << 3) + _pb_varint(0)
            + _pb_varint(3 << 3) + _pb_varint(server_id)
            + _pb_bytes(4, signature)
        )
        return key, iv, proto

    def _encrypt(self, data: bytes) -> bytes:
        if self._session_key is None or self._session_iv is None:
            raise ArcfoxIovError("not connected")
        return _aes_cbc_encrypt(self._session_key, self._session_iv, data)

    def _decrypt(self, data: bytes) -> bytes:
        if self._session_key is None or self._session_iv is None:
            raise ArcfoxIovError("not connected")
        return _aes_cbc_decrypt(self._session_key, self._session_iv, data)

    def query_online(self) -> bool | None:
        """Return whether the vehicle is currently online."""
        if self._socket is None:
            raise ArcfoxIovError("not connected")
        payload = _pb_string(1, self.vin)  # QueryProto.Query.vin
        self._socket.sendall(
            self._build_frame(2, MSG_ONLINE_QUERY, self._encrypt(payload), self._remote_token)
        )
        deadline = time.monotonic() + self.timeout
        for _ in range(6):
            msg_type, body_type, body = self._recv_frame(deadline)
            if msg_type == 2 and body_type == MSG_ONLINE_RESP:
                fields = _parse_proto(self._decrypt(body))
                return _proto_varint_field(fields, 3) == 1
        return None

    def query_full_state(self) -> dict[str, Any]:
        """Return the full read-only vehicle state as a normalized dict."""
        if self._socket is None:
            raise ArcfoxIovError("not connected")
        now = datetime.now()
        content = json.dumps(
            {
                "ST": now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "queryItems": _build_query_items(),
                "token": _make_query_token(self.vin, now),
                "vinNo": self.vin,
            },
            separators=(",", ":"),
        )
        # StringTransferProto.StringTransfer: seq=1, vin=2, content=3.
        payload = (
            _pb_varint(1 << 3) + _pb_varint(self._next_sequence())
            + _pb_string(2, self.vin)
            + _pb_string(3, content)
        )
        self._socket.sendall(
            self._build_frame(2, MSG_FULL_STATE_QUERY, self._encrypt(payload), self._remote_token)
        )
        deadline = time.monotonic() + self.timeout
        for _ in range(10):
            msg_type, body_type, body = self._recv_frame(deadline)
            if msg_type != 2 or body_type != MSG_FULL_STATE_RESP:
                continue
            fields = _parse_proto(self._decrypt(body))
            content_bytes = _proto_bytes_field(fields, 3)
            try:
                raw = json.loads(content_bytes.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError) as err:
                raise ArcfoxIovError("invalid full-state response") from err
            query_result = raw.get("queryResult")
            normalized = map_query_result(query_result) if isinstance(query_result, dict) else {}
            normalized.setdefault("vin", raw.get("vinNo") or self.vin)
            normalized["raw"] = raw
            return normalized
        raise ArcfoxIovError("no full-state response received")

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None
                self._session_key = None
                self._session_iv = None

    def __enter__(self) -> "ArcfoxIovClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
