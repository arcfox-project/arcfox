#!/usr/bin/env python3
"""Minimal MQTT probe for ARCFOX brokers."""

from __future__ import annotations

import argparse
import asyncio
import ssl
from dataclasses import dataclass


def _encode_utf8(value: str) -> bytes:
    data = value.encode("utf-8")
    return len(data).to_bytes(2, "big") + data


def _decode_utf8(data: bytes, offset: int = 0) -> tuple[str, int]:
    length = int.from_bytes(data[offset : offset + 2], "big")
    offset += 2
    end = offset + length
    return data[offset:end].decode("utf-8", errors="replace"), end


def _encode_remaining_length(length: int) -> bytes:
    out = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            return bytes(out)


async def _read_remaining_length(reader: asyncio.StreamReader) -> int:
    multiplier = 1
    value = 0
    while True:
        digit = (await reader.readexactly(1))[0]
        value += (digit & 0x7F) * multiplier
        if not digit & 0x80:
            return value
        multiplier *= 128


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first = (await reader.readexactly(1))[0]
    remaining = await _read_remaining_length(reader)
    payload = await reader.readexactly(remaining)
    return first, payload


@dataclass(slots=True)
class ProbeConfig:
    host: str
    port: int
    username: str
    password: str
    client_id: str
    topic: str
    timeout: int
    insecure: bool


async def run_probe(config: ProbeConfig) -> int:
    ssl_ctx: ssl.SSLContext | None = None
    if config.port == 8883:
        if config.insecure:
            ssl_ctx = ssl._create_unverified_context()
        else:
            ssl_ctx = ssl.create_default_context()

    reader, writer = await asyncio.open_connection(
        config.host,
        config.port,
        ssl=ssl_ctx,
    )
    try:
        variable = bytearray()
        variable.extend(_encode_utf8("MQTT"))
        variable.append(4)
        variable.append(0xC2)
        variable.extend((60).to_bytes(2, "big"))

        payload = bytearray()
        payload.extend(_encode_utf8(config.client_id))
        payload.extend(_encode_utf8(config.username))
        payload.extend(_encode_utf8(config.password))

        packet = bytearray([0x10])
        packet.extend(_encode_remaining_length(len(variable) + len(payload)))
        packet.extend(variable)
        packet.extend(payload)
        writer.write(packet)
        await writer.drain()

        packet_type, payload_bytes = await _read_packet(reader)
        if packet_type >> 4 != 2 or len(payload_bytes) < 2:
            print(f"unexpected CONNACK: packet_type={packet_type:#x} payload={payload_bytes!r}")
            return 2
        connack_code = payload_bytes[1]
        print(f"CONNACK return_code={connack_code}")
        if connack_code != 0:
            return 3

        packet_id = 1
        sub_payload = _encode_utf8(config.topic) + b"\x00"
        sub_variable = packet_id.to_bytes(2, "big")
        subscribe = bytearray([0x82])
        subscribe.extend(_encode_remaining_length(len(sub_variable) + len(sub_payload)))
        subscribe.extend(sub_variable)
        subscribe.extend(sub_payload)
        writer.write(subscribe)
        await writer.drain()

        packet_type, payload_bytes = await _read_packet(reader)
        if packet_type >> 4 != 9:
            print(f"unexpected SUBACK: packet_type={packet_type:#x} payload={payload_bytes!r}")
            return 4
        print(f"SUBACK payload={payload_bytes.hex()}")

        async def _ping_loop() -> None:
            while True:
                await asyncio.sleep(20)
                writer.write(b"\xC0\x00")
                await writer.drain()

        ping_task = asyncio.create_task(_ping_loop())
        try:
            while True:
                packet_type, payload_bytes = await asyncio.wait_for(
                    _read_packet(reader),
                    timeout=config.timeout,
                )
                msg_type = packet_type >> 4
                if msg_type == 3:
                    topic, pos = _decode_utf8(payload_bytes)
                    qos = (packet_type >> 1) & 0x03
                    if qos:
                        pos += 2
                    body = payload_bytes[pos:]
                    print(f"PUBLISH topic={topic} bytes={len(body)} hex={body[:64].hex()}")
                    try:
                        print(body.decode("utf-8"))
                    except UnicodeDecodeError:
                        pass
                elif msg_type == 13:
                    print("PINGRESP")
                else:
                    print(f"packet type={msg_type} raw={payload_bytes.hex()}")
        except TimeoutError:
            print(f"timeout waiting for messages on {config.topic}")
            return 0
        finally:
            ping_task.cancel()
    finally:
        writer.close()
        await writer.wait_closed()


def parse_args() -> ProbeConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8883)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--topic", default="#")
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()
    return ProbeConfig(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        client_id=args.client_id,
        topic=args.topic,
        timeout=args.timeout,
        insecure=args.insecure,
    )


def main() -> int:
    return asyncio.run(run_probe(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
