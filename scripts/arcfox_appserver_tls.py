#!/usr/bin/env python3
"""ARCFOX AppServer TLS 1.3 客户端（实验性）。

在已破解的传输层（5 字节混淆帧头 + 48 字节 XOR，见
``scripts/arcfox_appserver_codec.py``）之上手工实现 TLS 1.3 握手：

* X25519 密钥交换，TLS_AES_256_GCM_SHA384 (0x1302)
* SNI ``squnit-api-ai.jd.com`` + ALPN h2/http1.1

用途：验证 AppServer 传输层复刻是否正确，观察服务端握手后首个业务报文。
**不携带任何账号/车辆凭据。**

用法：:

    python3 scripts/arcfox_appserver_tls.py [host] [port]
"""

from __future__ import annotations

import hashlib
import hmac
import os
import socket
import struct
import sys

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, os.path.dirname(__file__))
from arcfox_appserver_codec import XOR_KEY, encode_frame, xor_keystream

HOST = "36.152.80.247"
PORT = 443
SNI = "squnit-api-ai.jd.com"

CONTENT_HANDSHAKE = 0x16
CONTENT_CCS = 0x14
CONTENT_APPDATA = 0x17
TLS_AES_256_GCM_SHA384 = 0x1302
GROUP_X25519 = 0x001D

HS_CLIENT_HELLO = 0x01
HS_SERVER_HELLO = 0x02
HS_ENCRYPTED_EXTENSIONS = 0x08
HS_CERTIFICATE = 0x0B
HS_CERTIFICATE_VERIFY = 0x0F
HS_FINISHED = 0x14


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def hkdf_expand_label(secret: bytes, label: bytes, context: bytes, length: int) -> bytes:
    full_label = b"tls13 " + label
    info = struct.pack(">H", length) + bytes([len(full_label)]) + full_label + bytes([len(context)]) + context
    out = b""
    t = b""
    counter = 1
    while len(out) < length:
        t = hmac_sha256(secret, t + info + bytes([counter]))
        out += t
        counter += 1
    return out[:length]


def derive_secret(secret: bytes, label: bytes, transcript: bytes) -> bytes:
    return hkdf_expand_label(secret, label, hashlib.sha256(transcript).digest(), 32)


class TLS13Session:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.priv = x25519.X25519PrivateKey.generate()
        self.pub = self.priv.public_key().public_bytes_raw()
        self.transcript = b""
        self.client_seq = 0
        self.server_seq = 0
        self.rbuf = b""

    # ---- transport ----
    def send_frame(self, content_type: int, body: bytes):
        self.sock.sendall(encode_frame(content_type, body))

    def recv_exact(self, n: int) -> bytes:
        while len(self.rbuf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError("connection closed")
            self.rbuf += chunk
        out, self.rbuf = self.rbuf[:n], self.rbuf[n:]
        return out

    def recv_frame(self) -> tuple[int, bytes]:
        head = self.recv_exact(5)
        content_type = head[0]
        if head[1:3] != b"\x5f\x58":
            raise ValueError(f"bad magic: {head.hex()}")
        encoded_len = struct.unpack(">H", head[3:5])[0]
        body_len = encoded_len ^ 0x5C5C
        return content_type, xor_keystream(self.recv_exact(body_len), XOR_KEY)

    @staticmethod
    def record_aad(content_type: int, body_len: int) -> bytes:
        # AAD = 5 字节混淆帧头（线上原样：长度已异或）
        return bytes([content_type, 0x5F, 0x58]) + struct.pack(">H", body_len ^ 0x5C5C)

    # ---- TLS helpers ----
    def build_client_hello(self) -> bytes:
        legacy_version = b"\x03\x03"
        random_bytes = os.urandom(32)
        session_id = b""
        cipher_suites = bytes.fromhex("130213011303c02bc02ccca9c02fc030cca8c013c014009c009d002f0035")
        compression = b"\x01\x00"

        sni = b"\x00" + struct.pack(">H", len(SNI) + 3) + b"\x00" + struct.pack(">H", len(SNI)) + SNI.encode()
        groups = struct.pack(">H", 2) + struct.pack(">H", GROUP_X25519)
        sigalgs = b"\x00\x08" + bytes.fromhex("040308040401050308050501080606010201")
        alpn = struct.pack(">H", 6) + b"\x02h2\x08http/1.1"
        versions = struct.pack(">H", 2) + b"\x03\x04"
        keyshare = struct.pack(">H", GROUP_X25519) + struct.pack(">H", len(self.pub)) + self.pub
        psk_modes = b"\x01\x01"

        def ext(etype: int, data: bytes) -> bytes:
            return struct.pack(">H", etype) + struct.pack(">H", len(data)) + data

        extensions = (
            ext(0x0000, sni)
            + ext(0x000A, groups)
            + ext(0x000D, sigalgs)
            + ext(0x0010, alpn)
            + ext(0x002B, versions)
            + ext(0x0033, keyshare)
            + ext(0x002D, psk_modes)
        )
        body = (
            legacy_version + random_bytes + bytes([len(session_id)]) + session_id
            + struct.pack(">H", len(cipher_suites)) + cipher_suites
            + compression + struct.pack(">H", len(extensions)) + extensions
        )
        return bytes([HS_CLIENT_HELLO]) + struct.pack(">I", len(body))[1:] + body

    def parse_server_hello(self, msg: bytes):
        pos = 4 + 2 + 32  # header + legacy_version + random
        sid_len = msg[pos]
        pos += 1 + sid_len
        cipher = struct.unpack(">H", msg[pos : pos + 2])[0]
        pos += 2 + 1
        ext_len = struct.unpack(">H", msg[pos : pos + 2])[0]
        pos += 2
        end = pos + ext_len
        server_share = None
        selected_version = None
        while pos + 4 <= end:
            etype = struct.unpack(">H", msg[pos : pos + 2])[0]
            elen = struct.unpack(">H", msg[pos + 2 : pos + 4])[0]
            pos += 4
            data = msg[pos : pos + elen]
            pos += elen
            if etype == 0x0033:
                klen = struct.unpack(">H", data[2:4])[0]
                server_share = data[4 : 4 + klen]
            elif etype == 0x002B:
                selected_version = data
        return cipher, server_share, selected_version

    def setup_keys(self, server_share: bytes):
        ecdhe = self.priv.exchange(x25519.X25519PublicKey.from_public_bytes(server_share))
        early_secret = hmac_sha256(b"\x00" * 32, b"\x00" * 32)
        derived = hkdf_expand_label(early_secret, b"derived", hashlib.sha256(b"").digest(), 32)
        hs_secret = hmac_sha256(derived, ecdhe)
        self.hs_secret = hs_secret
        c_hs_secret = derive_secret(hs_secret, b"c hs traffic", self.transcript)
        s_hs_secret = derive_secret(hs_secret, b"s hs traffic", self.transcript)
        self.client_hs_key = hkdf_expand_label(c_hs_secret, b"key", b"", 32)
        self.server_hs_key = hkdf_expand_label(s_hs_secret, b"key", b"", 32)
        self.client_hs_iv = hkdf_expand_label(c_hs_secret, b"iv", b"", 12)
        self.server_hs_iv = hkdf_expand_label(s_hs_secret, b"iv", b"", 12)
        self.finished_key = hkdf_expand_label(hs_secret, b"finished", b"", 32)

    def decrypt_record(self, key: bytes, iv: bytes, seq: int, body: bytes, aad: bytes) -> bytes:
        nonce = bytes(a ^ b for a, b in zip(iv, struct.pack(">Q", seq)))
        return AESGCM(key).decrypt(nonce, body, aad)

    def encrypt_record(self, key: bytes, iv: bytes, seq: int, plaintext: bytes, inner_type: int, aad: bytes) -> bytes:
        nonce = bytes(a ^ b for a, b in zip(iv, struct.pack(">Q", seq)))
        return AESGCM(key).encrypt(nonce, plaintext + bytes([inner_type]), aad)

    # ---- handshake ----
    def handshake(self):
        ch = self.build_client_hello()
        self.transcript += ch
        self.send_frame(CONTENT_HANDSHAKE, ch)
        self.send_frame(CONTENT_CCS, b"\x01")
        print("[*] ClientHello sent")

        # ServerHello
        while True:
            ct, body = self.recv_frame()
            if ct == CONTENT_CCS:
                continue
            if ct == CONTENT_HANDSHAKE:
                sh = body
                break
            if ct == CONTENT_APPDATA:
                print(f"[!] server sent 0x17 before ServerHello (len={len(body)})")
                continue
        print(f"[+] ServerHello: {sh[:16].hex()}...")
        cipher, server_share, selected_version = self.parse_server_hello(sh)
        print(f"[+] cipher=0x{cipher:04x} version={selected_version.hex() if selected_version else None}")
        self.transcript += sh
        self.setup_keys(server_share)

        # receive encrypted handshake flights until server Finished
        server_finished = None
        while server_finished is None:
            ct, body = self.recv_frame()
            if ct != CONTENT_APPDATA:
                print(f"[!] unexpected frame type 0x{ct:02x} in hs")
                continue
            aad = self.record_aad(CONTENT_APPDATA, len(body))
            try:
                plain = self.decrypt_record(self.server_hs_key, self.server_hs_iv, self.server_seq, body, aad)
            except Exception as exc:
                print(f"[!] decrypt server hs record failed: {exc}")
                print(f"    body len={len(body)} body[:32]={body[:32].hex()}")
                raise
            self.server_seq += 1
            inner_type = plain[-1]
            handshake_bytes = plain[:-1]
            self.transcript += handshake_bytes
            print(f"[+] server hs record: inner_type=0x{inner_type:02x} plaintext_len={len(handshake_bytes)}")
            if inner_type != CONTENT_HANDSHAKE:
                continue
            pos = 0
            while pos + 4 <= len(handshake_bytes):
                hst = handshake_bytes[pos]
                hslen = int.from_bytes(handshake_bytes[pos + 1 : pos + 4], "big")
                msg = handshake_bytes[pos : pos + 4 + hslen]
                print(f"    hs msg type=0x{hst:02x} len={hslen}")
                if hst == HS_FINISHED:
                    server_finished = msg
                pos += 4 + hslen

        # verify server Finished
        verify = server_finished[4:]
        expect = hmac_sha256(self.finished_key, hashlib.sha256(self.transcript).digest())
        print(f"[+] server Finished verify_data ok={hmac.compare_digest(verify, expect)}")

        # send client Finished (transcript includes server Finished)
        self.transcript += server_finished
        verify = hmac_sha256(self.finished_key, hashlib.sha256(self.transcript).digest())
        cfin = bytes([HS_FINISHED]) + struct.pack(">I", len(verify))[1:] + verify
        aad = self.record_aad(CONTENT_APPDATA, len(cfin) + 1 + 16)
        enc = self.encrypt_record(self.client_hs_key, self.client_hs_iv, self.client_seq, cfin, CONTENT_HANDSHAKE, aad)
        self.client_seq += 1
        self.send_frame(CONTENT_APPDATA, enc)
        self.transcript += cfin
        print("[+] client Finished sent")

        # application traffic secrets
        derived = hkdf_expand_label(self.hs_secret, b"derived", hashlib.sha256(b"").digest(), 32)
        self.app_secret = hmac_sha256(derived, b"\x00" * 32)
        c_app_secret = derive_secret(self.app_secret, b"c ap traffic", self.transcript)
        s_app_secret = derive_secret(self.app_secret, b"s ap traffic", self.transcript)
        self.client_app_key = hkdf_expand_label(c_app_secret, b"key", b"", 32)
        self.server_app_key = hkdf_expand_label(s_app_secret, b"key", b"", 32)
        self.client_app_iv = hkdf_expand_label(c_app_secret, b"iv", b"", 12)
        self.server_app_iv = hkdf_expand_label(s_app_secret, b"iv", b"", 12)
        print("[+] TLS 1.3 handshake completed")


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT
    print(f"[*] connecting {host}:{port} (SNI={SNI})")
    sock = socket.create_connection((host, port), timeout=20)
    sock.settimeout(20)
    sess = TLS13Session(sock)
    try:
        sess.handshake()
        try:
            ct, body = sess.recv_frame()
            print(f"[*] first post-handshake frame type=0x{ct:02x} len={len(body)} body[:32]={body[:32].hex()}")
        except socket.timeout:
            print("[*] no server data (server awaiting our business auth)")
    except Exception as exc:
        print(f"[!] failed: {exc!r}")
        return 1
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
