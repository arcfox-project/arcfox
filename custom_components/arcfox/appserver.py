"""ARCFOX AppServer vehicle-control channel (TCP 60115).

Reverse-engineered from the official Android app (3.4.28). The channel is a
plain TCP socket carrying protobuf-wrapped, AES-CBC-encrypted JSON control
orders. Only explicit vehicle-control commands are implemented here; the
read-only state queries live in :mod:`arcfox.iov`.

Credentials are supplied by the caller and never persisted by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import socket
import struct
import time
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

DEFAULT_HOST = "arcfoxapp-iov.bjev.com.cn"
DEFAULT_PORT = 60115
DEFAULT_APP_ID = "ae9db49b-7b8e-411d-ae16-e227a782b7af"
CONTROL_MSG_TYPE = -32752  # 0x8010, Control_car
MSG_CONTROL_RESULT = 20  # N60OrderResultResponse

FIXED_KEY = b"1234567812345678"
FIXED_IV = b"1234567812345678"


class ArcfoxAppServerError(Exception):
    """Base error for the AppServer control channel."""


class ArcfoxAppServerAuthError(ArcfoxAppServerError):
    """Authentication failed on the AppServer control channel."""


# ---------------------------------------------------------------------------
# Low-level crypto / protobuf helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _pb_varint(number: int) -> bytes:
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _pb_field_varint(num: int, value: int) -> bytes:
    return _pb_varint((num << 3) | 0) + _pb_varint(value)


def _pb_field_bytes(num: int, value: bytes) -> bytes:
    return _pb_varint((num << 3) | 2) + _pb_varint(len(value)) + value


def _pb_field_string(num: int, value: str) -> bytes:
    return _pb_field_bytes(num, value.encode("utf-8"))


def _pb_parse(buf: bytes) -> dict[int, Any]:
    out: dict[int, Any] = {}
    off = 0
    while off < len(buf):
        tag, off = _pb_read_varint(buf, off)
        num, wire = tag >> 3, tag & 7
        if wire == 0:
            value, off = _pb_read_varint(buf, off)
            out[num] = value
        elif wire == 2:
            length, off = _pb_read_varint(buf, off)
            out[num] = buf[off : off + length]
            off += length
        else:
            raise ArcfoxAppServerError(f"unsupported protobuf wire type {wire}")
    return out


def _pb_read_varint(buf: bytes, off: int) -> tuple[int, int]:
    number = 0
    shift = 0
    while True:
        byte = buf[off]
        off += 1
        number |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return number, off
        shift += 7


# ---------------------------------------------------------------------------
# Command mapping
#
# Transcribed from
# com.intest.valley.control.sdk.encapsulation.a.a(String, int, String)
# which dispatches ConstantUtil order types to AppServer CMD/body fields.
# ---------------------------------------------------------------------------

def _control_body(
    cmd: str,
    *,
    c: str | None = None,
    p1: str | None = None,
    p2: str | None = None,
) -> dict[str, str]:
    body: dict[str, str] = {}
    if c:
        body["C"] = c
    if p1:
        body["P1"] = p1
    if p2:
        body["P2"] = p2
    return body


APPSERVER_CONTROL_SPECS: dict[str, dict[str, Any]] = {
    # action -> {"cmd": ..., "body_builder": callable, "param": ...}
    "lock": {"cmd": "4", "body": _control_body("4", c="2", p1="1")},
    "unlock": {"cmd": "4", "body": _control_body("4", c="1", p1="1")},
    "trunk_open": {"cmd": "4", "body": _control_body("4", c="1", p1="2")},
    "flash_honk": {"cmd": "5", "body": _control_body("5", c="1")},
    "window_open": {"cmd": "6", "body": _control_body("6", c="1", p1="1")},
    "window_close": {"cmd": "6", "body": _control_body("6", c="2", p1="1")},
    "sunroof_open": {"cmd": "6", "body": _control_body("6", c="1", p2="1")},
    "sunroof_close": {"cmd": "6", "body": _control_body("6", c="2", p2="1")},
    "climate_on": {"cmd": "2", "body": _control_body("2", c="1")},
    "climate_off": {"cmd": "2", "body": _control_body("2", c="2")},
    "set_climate_temperature": {"cmd": "2", "body": _control_body("2", c="1")},
    "front_defrost_on": {"cmd": "3", "body": _control_body("3", c="1")},
    "front_defrost_off": {"cmd": "3", "body": _control_body("3", c="2")},
}


def _apply_climate_temperature(body: dict[str, str], temperature: float | int | None) -> dict[str, str]:
    if temperature is not None:
        body["P1"] = str(int(round(float(temperature))))
    return body


# ---------------------------------------------------------------------------
# Frame / handshake helpers
# ---------------------------------------------------------------------------

def _build_frame(
    order_type: int,
    imei: str,
    seq: int,
    msg_type: int,
    payload: bytes,
    vin: str,
    aid: int,
    token: str,
) -> bytes:
    if len(imei) != 15:
        raise ArcfoxAppServerError("IMEI must be 15 characters")
    if len(vin) != 17:
        raise ArcfoxAppServerError("VIN must be 17 characters")
    if len(token) != 32:
        raise ArcfoxAppServerError("app token must be 32 characters")
    header = (
        bytes([order_type, 8, 2])
        + imei.encode("ascii")
        + struct.pack("<H", seq)
        + struct.pack("<h", msg_type)
        + struct.pack("<I", len(payload))
    )
    trailer = vin.encode("ascii") + struct.pack("<Q", aid) + token.encode("ascii")
    return header + payload + trailer


def _parse_frame(buf: bytes) -> dict[str, Any]:
    if len(buf) < 26:
        raise ArcfoxAppServerError("short frame")
    payload_len = struct.unpack("<I", buf[22:26])[0]
    return {
        "order_type": buf[0],
        "imei": buf[3:18].decode("ascii", "replace"),
        "seq": struct.unpack("<H", buf[18:20])[0],
        "msg_type": struct.unpack("<h", buf[20:22])[0],
        "payload": buf[26 : 26 + payload_len],
    }


def _build_client_hello(seq: int, client_random: bytes, app_id: str) -> bytes:
    pre = b"\x01\x00" + struct.pack("<H", seq) + client_random
    signature = _aes_cbc_encrypt(FIXED_KEY, FIXED_IV, _sha256(pre))
    return (
        _pb_field_varint(1, seq)
        + _pb_field_bytes(2, client_random)
        + _pb_field_bytes(3, signature)
        + _pb_field_string(4, app_id)
    )


def _build_client_finish(
    seq: int, server_id: int, client_random: bytes, server_random: bytes
) -> tuple[bytes, bytes, bytes]:
    pre = b"\x03\x00" + struct.pack("<H", server_id) + b"\x00" + struct.pack("<H", seq)
    session_key = _md5(_xor(FIXED_KEY, client_random) + _md5(_xor(FIXED_KEY, server_random)))
    session_iv = _md5(client_random + FIXED_IV + server_random)
    signature = _aes_cbc_encrypt(session_key, session_iv, _sha256(pre))
    proto = (
        _pb_field_varint(1, seq)
        + _pb_field_varint(3, server_id)
        + _pb_field_bytes(4, signature)
    )
    return proto, session_key, session_iv


def build_control_json(
    *,
    cmd: str,
    body: dict[str, str],
    order_token: str,
    order_seq: int,
    now: datetime | None = None,
) -> str:
    """Build the compact ControlOrderBean JSON used by the App."""
    now = now or datetime.now()
    header = {
        "VER": "1",
        "GROUP": "10",
        "CMD": cmd,
        "TOKEN": order_token,
        "ST": now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "SEQ": str(order_seq),
        "DOWN": "1",
    }
    return json.dumps({"header": header, "body": body}, ensure_ascii=False, separators=(",", ":"))


def build_string_transfer(seq: int, vin: str, content: str) -> bytes:
    return (
        _pb_field_varint(1, seq)
        + _pb_field_string(2, vin)
        + _pb_field_string(3, content)
    )


def _make_order_token(vin: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return vin[-8:] + now.strftime("%y%m%d%H%M%S") + str(random.randint(1000, 9999))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class ArcfoxAppServerClient:
    """Synchronous AppServer control-channel client.

    One command per connection, mirroring how the official app opens a fresh
    socket for each control action.
    """

    def __init__(
        self,
        vin: str,
        app_token: str,
        aid: int,
        imei: str,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 20.0,
    ) -> None:
        self.vin = vin
        self.app_token = app_token
        self.aid = int(aid)
        self.imei = imei
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._session_key: bytes | None = None
        self._session_iv: bytes | None = None
        self._server_id: int | None = None
        self._client_random = os.urandom(16)
        self._seq = 0
        self._order_seq = random.randint(0, 1000)
        self._proto_seq = random.randint(0, 1000)

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFFFF
        return self._seq

    def connect(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)

    def _send(self, frame: bytes) -> None:
        if self._sock is None:
            raise ArcfoxAppServerError("not connected")
        self._sock.sendall(frame)

    def _recv_exact(self, length: int) -> bytes:
        if self._sock is None:
            raise ArcfoxAppServerError("not connected")
        buf = b""
        while len(buf) < length:
            chunk = self._sock.recv(length - len(buf))
            if not chunk:
                raise ArcfoxAppServerError("socket closed by server")
            buf += chunk
        return buf

    def _recv_frame(self) -> dict[str, Any]:
        header = self._recv_exact(26)
        payload_len = struct.unpack("<I", header[22:26])[0]
        payload = self._recv_exact(payload_len)
        return _parse_frame(header + payload)

    def handshake(self) -> None:
        if self._sock is None:
            self.connect()

        seq = self._next_seq()
        hello = _build_client_hello(seq, self._client_random, DEFAULT_APP_ID)
        self._send(_build_frame(1, self.imei, seq, 1, hello, self.vin, self.aid, self.app_token))

        response = self._recv_frame()
        if response["msg_type"] != 2:
            raise ArcfoxAppServerError(f"unexpected hello response msg_type={response['msg_type']}")
        fields = _pb_parse(response["payload"])
        if fields.get(2, 0) != 0:
            raise ArcfoxAppServerAuthError(f"ClientHello failed: {fields}")
        server_id = fields.get(3)
        server_random = fields.get(4)
        if not isinstance(server_id, int) or not isinstance(server_random, bytes):
            raise ArcfoxAppServerError("hello response missing serverId/serverRandom")

        seq = self._next_seq()
        finish, session_key, session_iv = _build_client_finish(
            seq, server_id, self._client_random, server_random
        )
        self._send(_build_frame(1, self.imei, seq, 3, finish, self.vin, self.aid, self.app_token))

        response = self._recv_frame()
        if response["msg_type"] != 4:
            raise ArcfoxAppServerError(f"unexpected finish response msg_type={response['msg_type']}")
        fields = _pb_parse(response["payload"])
        if fields.get(2, 0) != 0:
            raise ArcfoxAppServerAuthError(f"ClientFinish failed: {fields}")

        self._session_key = session_key
        self._session_iv = session_iv
        self._server_id = server_id

    def send_action(
        self,
        action: str,
        *,
        temperature: float | int | None = None,
        result_timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send one named control action and return the decoded result JSON."""
        spec = APPSERVER_CONTROL_SPECS.get(action)
        if spec is None:
            raise ArcfoxAppServerError(f"unsupported AppServer action: {action}")

        if self._session_key is None or self._session_iv is None:
            self.handshake()

        body = dict(spec["body"])
        if action in ("climate_on", "set_climate_temperature"):
            body = _apply_climate_temperature(body, temperature)
            if "P1" not in body:
                body["P1"] = "24"

        self._order_seq += 1
        content = build_control_json(
            cmd=spec["cmd"],
            body=body,
            order_token=_make_order_token(self.vin),
            order_seq=self._order_seq,
        )
        self._proto_seq += 1
        plain = build_string_transfer(self._proto_seq, self.vin, content)
        encrypted = _aes_cbc_encrypt(self._session_key, self._session_iv, plain)
        self._send(
            _build_frame(
                2,
                self.imei,
                self._next_seq(),
                CONTROL_MSG_TYPE,
                encrypted,
                self.vin,
                self.aid,
                self.app_token,
            )
        )

        deadline = time.monotonic() + result_timeout
        while time.monotonic() < deadline:
            try:
                response = self._recv_frame()
            except (ArcfoxAppServerError, TimeoutError, socket.timeout) as err:
                return {
                    "action": action,
                    "sent": True,
                    "result": None,
                    "error": str(err),
                }
            if response["msg_type"] != MSG_CONTROL_RESULT:
                continue
            try:
                plain = _aes_cbc_decrypt(self._session_key, self._session_iv, response["payload"])
            except Exception as err:  # pragma: no cover - defensive
                return {"action": action, "sent": True, "result": None, "error": f"decrypt: {err}"}
            fields = _pb_parse(plain)
            content_bytes = fields.get(3)
            if isinstance(content_bytes, bytes):
                try:
                    result = json.loads(content_bytes.decode("utf-8", "replace"))
                except (ValueError, UnicodeDecodeError) as err:
                    return {"action": action, "sent": True, "result": None, "error": f"bad json: {err}"}
                return {"action": action, "sent": True, "result": result}
        return {"action": action, "sent": True, "result": None, "error": "timeout"}

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._session_key = None
                self._session_iv = None
