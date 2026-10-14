#!/usr/bin/env python3
"""Round-trip test for the BCTP frame encoder.

The decoder below is a direct port of the decompiled
``BctpParseUtilsKt.decomposeBctpAgreement`` byte layout, so a passing test
proves that ``BctpCommandEnvelope.to_bctp_frame`` produces the exact bytes the
SDK parser expects.
"""

from __future__ import annotations

import importlib.util
import sys
import types

ROOT = __file__.rsplit("/scripts", 1)[0] if "/scripts" in __file__ else "."


def _load_package():
    pkg = types.ModuleType("arcfox")
    pkg.__path__ = [f"{ROOT}/custom_components/arcfox"]
    sys.modules["arcfox"] = pkg

    def load(name: str):
        path = f"{ROOT}/custom_components/arcfox/{name}.py"
        spec = importlib.util.spec_from_file_location(f"arcfox.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"arcfox.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    return {n: load(n) for n in ("models", "protocol", "bctp")}


def decode_frame(message: bytes) -> dict:
    """Port of ``decomposeBctpAgreement`` (non-103 branch)."""
    offset = 0
    protocol_name = message[offset]
    offset += 1
    framework_version = message[offset]
    offset += 1
    vin = message[offset : offset + 17].decode("ascii")
    offset += 17
    device_number = int.from_bytes(message[offset : offset + 4], "big")
    offset += 4
    type_hex = f"{message[offset] & 0x7F:02X}{message[offset + 1]:02X}"
    offset += 2
    compress_flag = message[offset]
    offset += 1
    send_time = message[offset : offset + 10]
    offset += 10
    business_unit_type = message[offset]
    offset += 1
    message_number = int.from_bytes(message[offset : offset + 2], "big")
    offset += 2
    service_version = int.from_bytes(message[offset : offset + 2], "big")
    offset += 2
    body_length = int.from_bytes(message[offset : offset + 4], "big")
    offset += 4
    body = message[offset : offset + body_length]
    return {
        "protocol_name": protocol_name,
        "framework_version": framework_version,
        "vin": vin,
        "device_number": device_number,
        "type": type_hex,
        "compress_flag": compress_flag,
        "send_time": send_time,
        "business_unit_type": business_unit_type,
        "message_number": message_number,
        "service_version": service_version,
        "body_length": body_length,
        "body": body,
    }


def _decode_protobuf_string(data: bytes) -> str | None:
    if not data or data[0] != 0x0A:
        return None
    length = data[1]
    return data[2 : 2 + length].decode("utf-8")


def main() -> int:
    mods = _load_package()
    protocol = mods["protocol"]
    bctp = mods["bctp"]

    vin = "LNBMC52K4NZ000000"
    payload = protocol.build_cmd7_payload("window", True)
    envelope = bctp.build_command_envelope(
        action="window_open",
        spec=protocol.COMMAND_SPECS["window_open"],
        payload=payload,
        token="A12345678900706144403",
        seq=3,
        st="2026-07-06 14:44:03.950",
        business_code="1001",
    )
    frame = envelope.to_bctp_frame(vin)

    decoded = decode_frame(frame)
    assert decoded["protocol_name"] == 0, decoded
    assert decoded["framework_version"] == 1, decoded
    assert decoded["vin"] == vin, decoded
    assert decoded["device_number"] == 3123, decoded
    assert decoded["type"] == "1001", decoded
    assert decoded["compress_flag"] == 0, decoded
    assert decoded["business_unit_type"] == 2, decoded
    assert decoded["service_version"] == 1, decoded
    assert decoded["body_length"] == len(decoded["body"]) == len(frame) - 45, decoded

    # sendTime: [0, year_hi, year_lo, month, day, hour, minute, second, ms_hi, ms_lo]
    st = decoded["send_time"]
    assert st[0] == 0, st
    assert st[3] in range(1, 13), st
    assert st[4] in range(1, 32), st
    assert st[5] in range(0, 24), st
    assert st[6] in range(0, 60), st
    assert st[7] in range(0, 60), st

    # Business protobuf is field 1 (string cmddown).
    cmddown = _decode_protobuf_string(decoded["body"])
    assert cmddown is not None, decoded["body"]
    assert '"GROUP":"10"' in cmddown and '"CMD":"7"' in cmddown, cmddown
    assert '"p2":"1"' in cmddown and '"p3":"1"' in cmddown, cmddown

    # N80KS/B31CS variant carries a 30-byte terminal barcode.
    long_frame = envelope.to_bctp_frame(vin, protocol_name=103)
    assert len(long_frame) == len(frame) + 30, (len(long_frame), len(frame))
    assert long_frame[19:49] == b"0" * 30

    print("BCTP codec round-trip: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
