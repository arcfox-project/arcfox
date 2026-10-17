#!/usr/bin/env python3
"""ARCFOX AppServer 传输层编解码器（已确认）。

背景
----
新版极狐 App（3.4.33+）的车控 SDK 不再只走 MQTT/BCTP，而是使用一个
「AppServer 自定义长连接」：

* 目标地址：``36.152.80.247:443``（DNS: ``squnit-api-ai.jd.com``，京东云托管）
* 传输层：**标准 TLS 1.3**，但每条 TLS record 外面再包一层 5 字节混淆头，
  且 record 内容与一个 **48 字节固定密钥** 做异或混淆。

5 字节帧头（big-endian，偏移 3..4 的长度被 0x5c5c 异或）：:

    byte0          = TLS 内容类型 (0x16 handshake / 0x14 CCS / 0x17 appdata)
    byte1          = 0x5f
    byte2          = 0x58
    byte3..4       = (payload_len ^ 0x5c5c) as uint16 BE
    payload[0..n]  = TLS record body XOR key[i % 48]

注意：这里的 payload 是 **TLS record body**（不含标准 5 字节 record 头），
即握手帧去混淆后是 TLS handshake message（ClientHello/ServerHello），
0x17 帧去混淆后是 TLS 1.3 AES-GCM 密文。

本脚本只实现「解包/重包」与「record 异或」，供后续 Python 客户端复刻使用。
不包含任何账号、VIN、token 等凭据。
"""

from __future__ import annotations

import struct

MAGIC = b"\x5f\x58"
LEN_XOR = 0x5C5C

# AppServer 传输层固定混淆密钥（48 字节，握手帧零填充区提取，双向一致）。
# 这是协议常量，非个人凭据。
XOR_KEY = bytes.fromhex(
    "1affaa3b2b1c4e2c5c1bfeab3a3c4ccc2c6b1afdac394c5c7a58591dfcad385c"
    "7c7b6c8a1efbae372a1a8a8b8a1ffaaf"
)

TLS_HANDSHAKE = 0x16
TLS_CHANGE_CIPHER_SPEC = 0x14
TLS_APPLICATION_DATA = 0x17


def xor_keystream(data: bytes, key: bytes = XOR_KEY) -> bytes:
    """对 payload 做循环异或（去混淆与加混淆是同一个操作）。"""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encode_frame(record_type: int, tls_record: bytes) -> bytes:
    """把一条 TLS record 包装成 AppServer 帧。

    ``tls_record`` 是标准 TLS record 字节（含 record 头 5 字节）。
    返回可直接写入 socket 的混淆帧。
    """
    n = len(tls_record)
    length_field = (n ^ LEN_XOR) & 0xFFFF
    header = bytes((record_type, MAGIC[0], MAGIC[1])) + struct.pack(">H", length_field)
    return header + xor_keystream(tls_record)


def iter_frames(data: bytes):
    """从字节流中切出 ``(record_type, payload_obfuscated)``。

    ``payload_obfuscated`` 是异或前的 record 内容；调用方可用 ``xor_keystream``
    还原成标准 TLS record。
    """
    off = 0
    while off + 5 <= len(data):
        record_type = data[off]
        if data[off + 1 : off + 3] != MAGIC:
            raise ValueError(f"bad magic at offset {off}: {data[off:off+5].hex()}")
        encoded_len = struct.unpack(">H", data[off + 3 : off + 5])[0]
        payload_len = encoded_len ^ LEN_XOR
        payload = data[off + 5 : off + 5 + payload_len]
        if len(payload) < payload_len:
            raise ValueError(f"truncated frame at offset {off}: want {payload_len}, got {len(payload)}")
        yield record_type, payload
        off += 5 + payload_len


def decode_stream(data: bytes) -> list[tuple[int, bytes]]:
    """解包整个流，返回 ``[(record_type, tls_record_plain), ...]``。"""
    return [(t, xor_keystream(p)) for t, p in iter_frames(data)]


def parse_tls_sni(handshake_message: bytes) -> str | None:
    """从 ClientHello handshake message 提取 SNI（仅供诊断）。"""
    if len(handshake_message) < 4 or handshake_message[0] != 0x01:  # ClientHello
        return None
    pos = 4 + 2 + 32  # handshake header + legacy_version + random
    if pos + 1 > len(handshake_message):
        return None
    sid_len = handshake_message[pos]
    pos += 1 + sid_len
    if pos + 2 > len(handshake_message):
        return None
    cs_len = int.from_bytes(handshake_message[pos : pos + 2], "big")
    pos += 2 + cs_len
    if pos + 1 > len(handshake_message):
        return None
    comp_len = handshake_message[pos]
    pos += 1 + comp_len
    if pos + 2 > len(handshake_message):
        return None
    ext_len = int.from_bytes(handshake_message[pos : pos + 2], "big")
    pos += 2
    end = pos + ext_len
    while pos + 4 <= min(end, len(handshake_message)):
        etype = int.from_bytes(handshake_message[pos : pos + 2], "big")
        elen = int.from_bytes(handshake_message[pos + 2 : pos + 4], "big")
        pos += 4
        if etype == 0 and pos + 5 <= len(handshake_message):
            name_len = int.from_bytes(handshake_message[pos + 3 : pos + 5], "big")
            return handshake_message[pos + 5 : pos + 5 + name_len].decode("ascii", "replace")
        pos += elen
    return None


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        data = open(path, "rb").read()
        print(f"=== {path} ({len(data)} bytes) ===")
        try:
            for i, (rtype, rec) in enumerate(decode_stream(data)):
                sni = parse_tls_sni(rec) if rtype == TLS_HANDSHAKE else None
                extra = f" SNI={sni}" if sni else ""
                print(f"  #{i:2d} type=0x{rtype:02x} len={len(rec):4d}{extra}")
        except ValueError as exc:
            print(f"  decode error: {exc}")
