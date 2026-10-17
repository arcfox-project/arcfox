#!/usr/bin/env python3
"""ARCFOX AppServer 车控通道客户端 (App 3.4.28 / com.intest.valley.control.sdk).

仅复刻协议，不内置任何真实凭据。凭据通过环境变量或参数传入：
  ARCFOX_IMEI / ARCFOX_VIN / ARCFOX_AID / ARCFOX_APP_TOKEN
"""
import os, socket, struct, hashlib, sys, json, random, datetime, time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

HOST_DEFAULT = "arcfoxapp-iov.bjev.com.cn"
PORT_DEFAULT = 60115
APP_ID = "ae9db49b-7b8e-411d-ae16-e227a782b7af"
CONTROL_MSG_TYPE = -32752  # Control_car = 0x8010
FIRST_KEY = b"1234567812345678"

# 从 App 3.4.28 反编译的 orderType -> AppServer CMD/body 映射。
# 仅包含已确认的简单控制指令；座椅/预约等走 SendOrderBean 通道。
COMMAND_TABLE = {
    "search-car": {"cmd": "5", "body": {"C": "1"}},
    "unlock": {"cmd": "4", "body": {"C": "1", "P1": "1"}},
    "lock": {"cmd": "4", "body": {"C": "2", "P1": "1"}},
    "trunk-open": {"cmd": "4", "body": {"C": "1", "P1": "2"}},
    "window-open": {"cmd": "6", "body": {"C": "1", "P1": "1"}},
    "window-close": {"cmd": "6", "body": {"C": "2", "P1": "1"}},
    "sunroof-open": {"cmd": "6", "body": {"C": "1", "P2": "1"}},
    "sunroof-close": {"cmd": "6", "body": {"C": "2", "P2": "1"}},
    "ac-on": {"cmd": "2", "body": {"C": "1", "P1": "24"}},
    "ac-off": {"cmd": "2", "body": {"C": "2"}},
    "defrost-on": {"cmd": "3", "body": {"C": "1"}},
    "defrost-off": {"cmd": "3", "body": {"C": "2"}},
}
FIRST_IV = b"1234567812345678"

# ---- 基础加密 ----

def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()

def md5(b: bytes) -> bytes:
    return hashlib.md5(b).digest()

def aes_cbc_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(padded) + enc.finalize()

def aes_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()

# ---- protobuf 手工编解码（仅用到 varint/bytes/string） ----

def pb_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)

def pb_field_varint(num: int, val: int) -> bytes:
    return pb_varint((num << 3) | 0) + pb_varint(val)

def pb_field_bytes(num: int, val: bytes) -> bytes:
    return pb_varint((num << 3) | 2) + pb_varint(len(val)) + val

def pb_field_string(num: int, val: str) -> bytes:
    return pb_field_bytes(num, val.encode())

def pb_read_varint(buf: bytes, off: int):
    shift = 0
    n = 0
    while True:
        b = buf[off]; off += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            return n, off
        shift += 7

def pb_parse(buf: bytes):
    """返回 {field_num: value}，value 为 int 或 bytes。"""
    out = {}
    off = 0
    while off < len(buf):
        tag, off = pb_read_varint(buf, off)
        num, wt = tag >> 3, tag & 7
        if wt == 0:
            val, off = pb_read_varint(buf, off)
            out[num] = val
        elif wt == 2:
            ln, off = pb_read_varint(buf, off)
            out[num] = buf[off:off+ln]
            off += ln
        else:
            raise ValueError(f"unsupported wire type {wt} field {num}")
    return out

# ---- 控制命令报文 ----

def build_string_transfer(seq: int, vin: str, content: str) -> bytes:
    """StringTransferProto: field1=seq, field2=vin, field3=content(JSON)。"""
    return (pb_field_varint(1, seq) +
            pb_field_string(2, vin) +
            pb_field_string(3, content))

# ---- 业务帧 ----

def build_frame(order_type: int, imei: str, seq: int, msg_type: int,
                payload: bytes, vin: str, aid: int, token: str) -> bytes:
    assert len(imei) == 15, "IMEI must be 15 chars"
    assert len(vin) == 17, "VIN must be 17 chars"
    assert len(token) == 32, "APP_TOKEN must be 32 chars"
    return (bytes([order_type, 8, 2]) +
            imei.encode() +
            struct.pack("<H", seq) +
            struct.pack("<h", msg_type) +
            struct.pack("<I", len(payload)) +
            payload +
            vin.encode() +
            struct.pack("<Q", aid) +
            token.encode())

def parse_frame(buf: bytes):
    """返回 dict(order_type, imei, seq, msg_type, payload)。msg_type 为有符号 short。"""
    return {
        "order_type": buf[0],
        "imei": buf[3:18].decode(),
        "seq": struct.unpack("<H", buf[18:20])[0],
        "msg_type": struct.unpack("<h", buf[20:22])[0],
        "payload": buf[26:26 + struct.unpack("<I", buf[22:26])[0]],
    }

# ---- 握手 ----

def build_client_hello(seq: int, client_random: bytes) -> bytes:
    b = b"\x01\x00" + struct.pack("<H", seq) + client_random
    sig = aes_cbc_encrypt(sha256(b), FIRST_KEY, FIRST_IV)
    return (pb_field_varint(1, seq) +
            pb_field_bytes(2, client_random) +
            pb_field_bytes(3, sig) +
            pb_field_string(4, APP_ID))

def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def build_client_finish(seq: int, server_id: int, client_random: bytes,
                        server_random: bytes):
    b = b"\x03\x00" + struct.pack("<H", server_id) + b"\x00" + struct.pack("<H", seq)
    session_key = md5(xor_bytes(FIRST_KEY, client_random) + md5(xor_bytes(FIRST_KEY, server_random)))
    session_iv = md5(client_random + FIRST_IV + server_random)
    sig = aes_cbc_encrypt(sha256(b), session_key, session_iv)
    msg = (pb_field_varint(1, seq) +
           pb_field_varint(3, server_id) +
           pb_field_bytes(4, sig))
    return msg, session_key, session_iv

# ---- 客户端 ----

class ArcfoxControlClient:
    def __init__(self, imei, vin, aid, token, host=HOST_DEFAULT, port=PORT_DEFAULT):
        self.imei = imei
        self.vin = vin
        self.aid = int(aid)
        self.token = token
        self.host = host
        self.port = port
        self.seq = 0
        self.sock = None
        self.session_key = None
        self.session_iv = None
        self.server_id = None
        self.client_random = os.urandom(16)
        self.order_seq = random.randint(0, 1000)
        self.proto_seq = random.randint(0, 1000)

    def _next_seq(self):
        self.seq = (self.seq + 1) & 0xFFFF
        return self.seq

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=15)
        self.sock.settimeout(15)
        return self

    def _send(self, frame: bytes):
        self.sock.sendall(frame)

    def _recv_frame(self):
        hdr = self._recv_exact(26)
        payload_len = struct.unpack("<I", hdr[22:26])[0]
        payload = self._recv_exact(payload_len)
        return parse_frame(hdr + payload)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed")
            buf += chunk
        return buf

    def handshake(self):
        seq = self._next_seq()
        hello = build_client_hello(seq, self.client_random)
        frame = build_frame(1, self.imei, seq, 1, hello, self.vin, self.aid, self.token)
        self._send(frame)

        resp = self._recv_frame()
        if resp["msg_type"] != 2:
            raise RuntimeError(f"expected ClientHelloResponse(msg_type=2), got {resp['msg_type']}")
        fields = pb_parse(resp["payload"])
        result = fields.get(2, 0)
        server_id = fields.get(3)
        server_random = fields.get(4)
        if result != 0:
            raise RuntimeError(f"ClientHello failed, result={result} fields={fields}")
        if server_id is None or server_random is None:
            raise RuntimeError(f"no serverId/serverRandom in response: {fields}")

        seq = self._next_seq()
        finish, sk, siv = build_client_finish(seq, server_id, self.client_random, server_random)
        frame = build_frame(1, self.imei, seq, 3, finish, self.vin, self.aid, self.token)
        self._send(frame)

        resp = self._recv_frame()
        if resp["msg_type"] != 4:
            raise RuntimeError(f"expected ClientFinishResponse(msg_type=4), got {resp['msg_type']}")
        fields = pb_parse(resp["payload"])
        result = fields.get(2, 0)
        if result != 0:
            raise RuntimeError(f"ClientFinish failed, result={result} fields={fields}")

        self.session_key = sk
        self.session_iv = siv
        self.server_id = server_id
        return fields

    def next_order_seq(self):
        self.order_seq += 1
        return self.order_seq

    def order_token(self):
        ts = datetime.datetime.now().strftime("%y%m%d%H%M%S")
        return self.vin[-8:] + ts + str(random.randint(1000, 9999))

    def build_control_json(self, cmd: str, body: dict):
        """按 ControlOrderBean 结构构造控制指令 JSON。"""
        header = {
            "VER": "1",
            "GROUP": "10",
            "CMD": cmd,
            "TOKEN": self.order_token(),
            "ST": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "SEQ": str(self.next_order_seq()),
            "DOWN": "1",
        }
        return json.dumps({"header": header, "body": body}, ensure_ascii=False, separators=(",", ":"))

    def send_control_command(self, cmd: str, body: dict, timeout: float = 20.0):
        """发送车控命令，读取到 N60OrderResultResponse(msgType=20) 后返回。

        返回 {"msg_type": int, "seq": int, "content": str|None, "raw": bytes}。
        """
        content = self.build_control_json(cmd, body)
        self.proto_seq += 1
        plain = build_string_transfer(self.proto_seq, self.vin, content)
        enc = aes_cbc_encrypt(plain, self.session_key, self.session_iv)
        frame = build_frame(2, self.imei, self._next_seq(), CONTROL_MSG_TYPE,
                            enc, self.vin, self.aid, self.token)
        self._send(frame)

        old_timeout = self.sock.gettimeout()
        if old_timeout is not None and old_timeout < max(timeout, 30):
            self.sock.settimeout(max(timeout, 30))
        deadline = time.time() + timeout
        seen = []
        while time.time() < deadline:
            try:
                resp = self._recv_frame()
            except Exception as e:
                return {"msg_type": None, "seq": None, "content": None,
                        "raw": None, "seen": seen, "error": repr(e)}
            mt = resp["msg_type"]
            seen.append(mt)
            try:
                dec = aes_cbc_decrypt(resp["payload"], self.session_key, self.session_iv)
            except Exception:
                dec = resp["payload"]
            if mt in (20, 12, 9, 19):
                fields = pb_parse(dec)
                content = None
                if 3 in fields and isinstance(fields[3], bytes):
                    content = fields[3].decode("utf-8", "replace")
                elif 4 in fields and isinstance(fields[4], bytes):
                    content = fields[4].decode("utf-8", "replace")
                return {"msg_type": mt, "seq": resp["seq"],
                        "content": content, "raw": dec, "seen": seen}
        return {"msg_type": None, "seq": None, "content": None,
                "raw": None, "seen": seen}

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


def main():
    imei = os.environ.get("ARCFOX_IMEI", "").strip()
    vin = os.environ.get("ARCFOX_VIN", "").strip()
    aid = os.environ.get("ARCFOX_AID", "").strip()
    token = os.environ.get("ARCFOX_APP_TOKEN", "").strip()
    host = os.environ.get("ARCFOX_APPSERVER_HOST", HOST_DEFAULT)
    port = int(os.environ.get("ARCFOX_APPSERVER_PORT", PORT_DEFAULT))
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    missing = [k for k, v in (("ARCFOX_IMEI", imei), ("ARCFOX_VIN", vin),
                              ("ARCFOX_AID", aid), ("ARCFOX_APP_TOKEN", token)) if not v]
    if missing:
        print(f"缺少凭据环境变量: {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

    c = ArcfoxControlClient(imei, vin, aid, token, host, port)
    print(f"连接 {host}:{port} ...")
    c.connect()
    print("开始握手 ...")
    fields = c.handshake()
    print(f"握手成功 serverId={c.server_id}")
    print(f"session_key={c.session_key.hex()}")
    print(f"session_iv={c.session_iv.hex()}")

    spec = COMMAND_TABLE.get(action)
    if spec is None:
        available = ", ".join(COMMAND_TABLE)
        print(f"未知动作: {action}，可用: {available}", file=sys.stderr)
        c.close()
        sys.exit(2)

    print(f"发送 {action} 指令 (CMD={spec['cmd']}, body={spec['body']}) ...")
    result = c.send_control_command(spec["cmd"], spec["body"])
    print("响应:", json.dumps(result, ensure_ascii=False, default=str))
    if result.get("content"):
        try:
            print("响应JSON:", json.dumps(json.loads(result["content"]), ensure_ascii=False, indent=2))
        except Exception:
            print("响应原文:", result["content"])
    c.close()

if __name__ == "__main__":
    main()
