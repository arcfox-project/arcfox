"""Minimal async MQTT publisher for ARCFOX BCTP commands."""

from __future__ import annotations

import asyncio
import json
import secrets
import ssl
from dataclasses import dataclass
from typing import Any


class ArcfoxMqttError(Exception):
    """MQTT transport error."""


@dataclass(frozen=True, slots=True)
class ArcfoxMqttConfig:
    """Connection settings for a bare MQTT broker."""

    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    keepalive: int = 60
    use_tls: bool = False


def _encode_utf8_string(value: str) -> bytes:
    data = value.encode("utf-8")
    return len(data).to_bytes(2, "big") + data


def _encode_remaining_length(length: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            digit |= 0x80
        encoded.append(digit)
        if length <= 0:
            return bytes(encoded)


def _serialize_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


class ArcfoxMqttPublisher:
    """Minimal MQTT 3.1.1 publisher for BCTP envelopes."""

    def __init__(self, config: ArcfoxMqttConfig) -> None:
        self._config = config
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

    async def connect(self) -> None:
        """Establish a broker connection if needed."""
        if self._connected and self._writer is not None and not self._writer.is_closing():
            return

        ssl_context = ssl.create_default_context() if self._config.use_tls else None
        self._reader, self._writer = await asyncio.open_connection(
            self._config.host,
            self._config.port,
            ssl=ssl_context,
        )
        client_id = self._config.client_id or f"arcfox-{secrets.token_hex(8)}"

        variable_header = bytearray()
        variable_header.extend(_encode_utf8_string("MQTT"))
        variable_header.append(4)
        connect_flags = 0x02
        if self._config.username:
            connect_flags |= 0x80
        if self._config.password:
            connect_flags |= 0x40
        variable_header.append(connect_flags)
        variable_header.extend(self._config.keepalive.to_bytes(2, "big"))

        payload = bytearray()
        payload.extend(_encode_utf8_string(client_id))
        if self._config.username:
            payload.extend(_encode_utf8_string(self._config.username))
        if self._config.password:
            payload.extend(_encode_utf8_string(self._config.password))

        packet = bytearray()
        packet.append(0x10)
        packet.extend(_encode_remaining_length(len(variable_header) + len(payload)))
        packet.extend(variable_header)
        packet.extend(payload)

        self._writer.write(packet)
        await self._writer.drain()

        connack = await self._reader.readexactly(4)
        if connack[0] != 0x20 or connack[1] != 0x02 or connack[3] != 0x00:
            raise ArcfoxMqttError(f"MQTT broker rejected connection: {connack!r}")

        self._connected = True

    async def publish(self, topic: str, payload: dict[str, Any] | bytes, *, qos: int = 1, retain: bool = False) -> None:
        """Publish a JSON payload to a topic."""
        if qos not in {0, 1}:
            raise ArcfoxMqttError("This publisher supports QoS 0 and 1 only")

        await self.connect()
        if self._writer is None:
            raise ArcfoxMqttError("MQTT writer not available")

        packet = bytearray()
        fixed_header = 0x30 | (0x02 if qos == 1 else 0x00) | (0x01 if retain else 0x00)
        packet.append(fixed_header)

        payload_bytes = payload if isinstance(payload, bytes) else _serialize_payload(payload)
        variable_header = _encode_utf8_string(topic)
        if qos == 1:
            packet_id = secrets.randbelow(65535) + 1
            variable_header += packet_id.to_bytes(2, "big")
        packet.extend(_encode_remaining_length(len(variable_header) + len(payload_bytes)))
        packet.extend(variable_header)
        packet.extend(payload_bytes)

        self._writer.write(packet)
        await self._writer.drain()
        if qos == 1 and self._reader is not None:
            ack = await asyncio.wait_for(self._reader.readexactly(4), timeout=10)
            if ack[0] != 0x40 or ack[1] != 0x02:
                raise ArcfoxMqttError(f"MQTT broker rejected publish: {ack!r}")

    async def close(self) -> None:
        """Close the broker connection."""
        if self._writer is None:
            return
        self._writer.close()
        try:
            await self._writer.wait_closed()
        finally:
            self._reader = None
            self._writer = None
            self._connected = False
