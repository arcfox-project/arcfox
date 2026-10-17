#!/usr/bin/env python3
"""ARCFOX AppServer 长连接：可完成握手的最小复刻客户端（实验性）。

2026-10-15 实测结论
--------------------
* AppServer 长连接（36.152.80.247:443）的 TLS 1.3 外观握手**必须**携带
  自定义扩展 ``0x0020``（61 字节，疑似压缩后的设备/会话指纹），否则服务端
  直接 ``alert(protocol_version)`` 或断连。
* 该扩展内容不在本仓库中；本脚本从 ``--x20`` 指定的文件读取（默认
  ``/tmp/arcfox_x20.bin``），避免把疑似设备指纹的字节提交进仓库。
* 当前只复刻到「ServerHello + CCS + 首个 0x17」；0x17 业务记录已被证明
  **不是标准 TLS 1.3 AES-GCM**，密钥派生仍在逆向中（见
  ``ARCFOX_逆向进展_20261015.md``）。

用法::

    python3 scripts/arcfox_appserver_handshake.py [--x20 /tmp/arcfox_x20.bin] [host] [port]

依赖: ``cryptography``。
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

from cryptography.hazmat.primitives.asymmetric import x25519

sys.path.insert(0, os.path.dirname(__file__))
from arcfox_appserver_codec import encode_frame, xor_keystream

HOST = "36.152.80.247"
PORT = 443

# 自定义扩展 0x0020 的默认存放位置（不提交仓库）。
X20_DEFAULT = "/tmp/arcfox_x20.bin"


def build_client_hello(pub: bytes, x20: bytes) -> bytes:
    legacy = b"\x03\x04"
    random_bytes = os.urandom(32)
    session_id = os.urandom(32)
    cipher_suites = bytes.fromhex(
        "130113021303c02bc02ccca9c02fc030cca8c013c014009c009d002f0035"
    )
    compression = b"\x01\x00"

    sni = struct.pack(">H", 23) + b"\x00" + struct.pack(">H", 20) + b"squnit-api-ai.jd.com"
    groups = b"\x00\x06" + bytes.fromhex("001d00170018")
    ec_point_formats = b"\x01\x00"
    alpn = b"\x00\x0c" + b"\x02h2\x08http/1.1"
    status_request = b"\x01\x00\x00\x00\x00"
    sigalgs = b"\x00\x12" + bytes.fromhex("040308040401050308050501080606010201")
    keyshare = b"\x00\x24" + struct.pack(">H", 0x001D) + b"\x00\x20" + pub
    psk_modes = b"\x01\x01"
    supported_versions = b"\x04\x03\x04\x03\x03"
    padding = b"\x00" * 172

    def ext(etype: int, data: bytes) -> bytes:
        return struct.pack(">H", etype) + struct.pack(">H", len(data)) + data

    extensions = (
        ext(0x0000, sni)
        + ext(0x0017, b"")
        + ext(0xFF01, b"\x00")
        + ext(0x000A, groups)
        + ext(0x000B, ec_point_formats)
        + ext(0x0010, alpn)
        + ext(0x0005, status_request)
        + ext(0x000D, sigalgs)
        + ext(0x0033, keyshare)
        + ext(0x002D, psk_modes)
        + ext(0x002B, supported_versions)
        + ext(0x0020, x20)
        + ext(0x0015, padding)
    )
    body = (
        legacy
        + random_bytes
        + bytes([len(session_id)])
        + session_id
        + struct.pack(">H", len(cipher_suites))
        + cipher_suites
        + compression
        + struct.pack(">H", len(extensions))
        + extensions
    )
    return bytes([0x01]) + struct.pack(">I", len(body))[1:] + body


def recv_frame(sock: object) -> tuple[int, bytes]:
    def exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise EOFError("connection closed")
            buf += chunk
        return buf

    head = exact(5)
    if head[1:3] != b"\x5f\x58":
        raise ValueError(f"bad magic: {head.hex()}")
    length = int.from_bytes(head[3:5], "big") ^ 0x5C5C
    return head[0], xor_keystream(exact(length))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x20", default=X20_DEFAULT)
    parser.add_argument("host", nargs="?", default=HOST)
    parser.add_argument("port", nargs="?", type=int, default=PORT)
    args = parser.parse_args()

    x20 = open(args.x20, "rb").read()
    if len(x20) != 61:
        print(f"[!] 0x0020 扩展应为 61 字节，实际 {len(x20)} 字节：{args.x20}", file=sys.stderr)

    import socket

    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes_raw()
    client_hello = build_client_hello(pub, x20)
    print(f"[*] ClientHello {len(client_hello)} bytes -> {args.host}:{args.port}")

    sock = socket.create_connection((args.host, args.port), timeout=15)
    sock.settimeout(15)
    sock.sendall(encode_frame(0x16, client_hello))
    sock.sendall(encode_frame(0x14, b"\x01"))

    for i in range(6):
        try:
            ctype, body = recv_frame(sock)
        except EOFError:
            print("[!] connection closed by server")
            break
        print(f"[+] frame#{i} type=0x{ctype:02x} len={len(body)} head={body[:12].hex()}")
        if ctype == 0x15:
            print(f"[!] server alert: {body.hex()}")
            break
        if ctype == 0x17 and i >= 2:
            break
    sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
