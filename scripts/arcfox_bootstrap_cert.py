#!/usr/bin/env python3
"""ARCFOX MQTT 客户端证书自助申请/换发脚本。

背景
----
ARCFOX（极狐）App 的 MQTT broker 要求双向 TLS。登录后 App 会调用
``POST /auth/signin``，把本地生成的 CSR（``p10``）交给服务端签发客户端证书：

* ``POST /auth/signinsms``  请求短信验证码，body: ``{userId, vin}``
* ``POST /auth/signin``     用验证码换证书/令牌，body: ``{userId, vin, smsCode, p10}``

私钥在本地生成、不上传，因此只要知道手机号 + VIN + 短信验证码，就能在任意
客户端申请/换发属于自己的 MQTT 客户端证书，无需 root/导出手机。

用法
----
1) 仅请求验证码（会自动发起短信）::

    python3 scripts/arcfox_bootstrap_cert.py --user-id 13800000000 --vin LNBSCB3F0XXXXXXX --model be12

2) 直接换发证书（把验证码作为参数传入）::

    python3 scripts/arcfox_bootstrap_cert.py --user-id 13800000000 --vin LNBSCB3F0XXXXXXX --sms-code 123456 --model be12

3) 已有本地证书、只需刷新 accessToken（MQTT 密码）::

    python3 scripts/arcfox_bootstrap_cert.py --user-id 13800000000 --vin LNBSCB3F0XXXXXXX --sms-code 123456 --refresh

结果
----
生成 ``<userId>.crt`` 与 ``<userId>.key``，并打印 MQTT 地址 / 用户名 / 密码，
供 ``scripts/arcfox_mqtt_probe.py`` 或 Home Assistant 集成使用。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    _HAS_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover
    _HAS_CRYPTOGRAPHY = False

# 各车型平台的生产环境默认配置（与 APK 反编译一致）
PLATFORMS = {
    "be12": {
        "label": "极狐 BE12 平台（阿尔法S/阿尔法T 等）",
        "base_pro": "https://sdkserver-be12.bjev.com.cn/api",
        "base_test": "https://sdkserver-be12-test.bjev.com.cn/api",
        "mqtt_pro": "ssl://emqx-be12.bjev.com.cn:8883",
        "mqtt_test": "ssl://emqx-be12-test.bjev.com.cn:8883",
    },
    "n5": {
        "label": "N5 平台",
        "base_pro": "https://sdkserver-n5.bjev.com.cn/api",
        "base_test": "https://sdkserver-n5-test.bjev.com.cn/api",
        "mqtt_pro": "ssl://emqx-n5.bjev.com.cn:8883",
        "mqtt_test": "ssl://emqx-test.bjev.com.cn:8883",
    },
    "n80": {
        "label": "N80 平台（考拉 KAOLA 等）",
        "base_pro": "https://sdkserver-n80.bjev.com.cn/api",
        "base_test": "https://sdkserver-n80-test.bjev.com.cn/api",
        "mqtt_pro": "ssl://emqx-n8.bjev.com.cn:8883",
        "mqtt_test": "ssl://emqx-test.bjev.com.cn:8883",
    },
    "c46": {
        "label": "C46 平台（考拉 KAOLA applibrary）",
        "base_pro": "https://sdkserver.bjev.com.cn/api",
        "base_test": "https://sdkserver-test.bjev.com.cn/api",
        "mqtt_pro": "ssl://emqx-c46.bjev.com.cn:8883",
        "mqtt_test": "ssl://emqx-test-c46.bjev.com.cn:8883",
    },
}

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "volley/0",
    "Accept": "application/json",
}


def default_base(model: str, env: str) -> str:
    key = f"base_{env}"
    return PLATFORMS[model][key]


def default_mqtt_host(model: str, env: str) -> str:
    key = f"mqtt_{env}"
    return PLATFORMS[model][key]


def gen_csr(subject: str) -> tuple[str, str]:
    """生成 RSA-2048 + SHA1WithRSA 的 PKCS#10 CSR，返回 (csr_pem, pkcs8_key_pem)。

    与 App 中 ``CsrUtil.genCSR("C=CN, CN=MOBILE_<userId>_<ts>")`` 等价。
    优先使用 openssl（保证 sha1WithRSAEncryption），缺失时回退 cryptography(SHA256)。
    """
    cn = subject.split("CN=", 1)[1].strip()

    try:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            key_path = tmp / "key.pem"
            csr_path = tmp / "csr.pem"
            subprocess.run(
                ["openssl", "req", "-new", "-nodes", "-newkey", "rsa:2048",
                 "-keyout", str(key_path), "-out", str(csr_path),
                 "-subj", f"/C=CN/CN={cn}", "-sha1"],
                check=True,
                capture_output=True,
            )
            key_pem = subprocess.run(
                ["openssl", "pkcs8", "-topk8", "-nocrypt", "-in", str(key_path)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            return csr_path.read_text(), key_pem
    except Exception as exc:
        if not _HAS_CRYPTOGRAPHY:
            raise RuntimeError("openssl 与 cryptography 均不可用，无法生成 CSR") from exc

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
                    x509.NameAttribute(NameOID.COMMON_NAME, cn),
                ]
            )
        )
        .sign(key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    return csr_pem, key_pem


def csr_to_p10(csr_pem: str) -> str:
    """去掉 CSR 的 PEM 头尾与所有空白，得到 base64 单行 p10。"""
    body = csr_pem.replace("-----BEGIN CERTIFICATE REQUEST-----", "")
    body = body.replace("-----END CERTIFICATE REQUEST-----", "")
    return re.sub(r"(\r\n|\n|\r|\s)", "", body)


def wrap_pem_certificate(base64_body: str) -> str:
    body = re.sub(r"(\r\n|\n|\r|\s)", "", base64_body)
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----\n"


def _post_json(base: str, path: str, body: dict, trace_id: str, session: requests.Session) -> dict:
    url = f"{base.rstrip('/')}{path}"
    headers = dict(DEFAULT_HEADERS)
    headers["baic_traceId"] = trace_id
    if args_verbose:
        print(f"[http] POST {url}", file=sys.stderr)
        print(f"[http] headers={json.dumps(headers, ensure_ascii=False)}", file=sys.stderr)
        print(f"[http] body={json.dumps(body, ensure_ascii=False)}", file=sys.stderr)
    resp = session.post(url, headers=headers, json=body, timeout=20)
    text = resp.text
    if args_verbose:
        print(f"[http] status={resp.status_code} body={text}", file=sys.stderr)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        print(f"非 JSON 响应：{text}", file=sys.stderr)
        raise


def is_success(data: dict) -> bool:
    return str(data.get("code")) in ("0", "200") or str(data.get("statusCode")) == "0"


def request_sms_code(base: str, user_id: str, vin: str, session: requests.Session) -> dict:
    body = {
        "userId": user_id,
        "vin": vin,
        "requestSettings": {"handleError": True, "timeOutMs": 15000},
    }
    return _post_json(base, "/auth/signinsms", body, str(uuid.uuid4()), session)


def signin(base: str, user_id: str, vin: str, sms_code: str, p10: str | None, session: requests.Session) -> dict:
    body = {
        "userId": user_id,
        "vin": vin,
        "smsCode": sms_code,
        "requestSettings": {"handleError": True, "timeOutMs": 15000},
    }
    if p10:
        body["p10"] = p10
    return _post_json(base, "/auth/signin", body, str(uuid.uuid4()), session)


args_verbose = False


def main() -> int:
    global args_verbose

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", required=True, help="账号 userId（通常是手机号）")
    parser.add_argument("--vin", required=True, help="车辆 VIN（17 位）")
    parser.add_argument("--sms-code", help="短信验证码；不传则脚本先发起验证码再交互输入")
    parser.add_argument("--model", choices=sorted(PLATFORMS), default="be12", help="车型平台，决定默认服务器地址")
    parser.add_argument("--env", choices=["pro", "test"], default="pro", help="生产/测试环境")
    parser.add_argument("--base", help="API 基础地址（覆盖 model/env 推断），例如 https://sdkserver-be12.bjev.com.cn/api")
    parser.add_argument("--out", default=".", help="证书输出目录")
    parser.add_argument("--refresh", action="store_true", help="已有本地证书，仅刷新 accessToken（不带 p10）")
    parser.add_argument("--no-send-sms", action="store_true", help="不调用 signinsms（验证码已由其它方式获取）")
    parser.add_argument("--dry-run", action="store_true", help="只生成 CSR，不发起任何网络请求")
    parser.add_argument("--verbose", action="store_true", help="打印完整请求/响应")
    args = parser.parse_args()
    args_verbose = args.verbose

    if requests is None:
        print("缺少 requests 库：pip install requests", file=sys.stderr)
        return 2

    base = args.base or default_base(args.model, args.env)
    mqtt_host = default_mqtt_host(args.model, args.env)
    print(f"平台：{PLATFORMS[args.model]['label']}（--model={args.model} --env={args.env}）")
    print(f"API  ：{base}")
    print(f"MQTT ：{mqtt_host}")

    if args.dry_run:
        csr_pem, key_pem = gen_csr(f"C=CN, CN=MOBILE_{args.user_id}_{int(time.time() * 1000)}")
        print("CSR（p10 前 80 字符）：", csr_to_p10(csr_pem)[:80])
        print("私钥前 80 字符：", key_pem.splitlines()[1][:80])
        return 0

    session = requests.Session()
    sms_code = args.sms_code
    if not sms_code and not args.no_send_sms:
        data = request_sms_code(base, args.user_id, args.vin, session)
        print(f"signinsms 响应：{json.dumps(data, ensure_ascii=False)}")
        if not is_success(data):
            print("验证码请求返回失败，请检查 userId / VIN / 车型平台(--model)是否正确。", file=sys.stderr)
            return 3
    if not sms_code:
        sms_code = input("请输入收到的短信验证码：").strip()
        if not sms_code:
            print("未输入验证码。", file=sys.stderr)
            return 4

    if args.refresh:
        data = signin(base, args.user_id, args.vin, sms_code, None, session)
        if not is_success(data):
            print(f"signin 失败：{json.dumps(data, ensure_ascii=False)}", file=sys.stderr)
            return 5
        token = (data.get("data") or {}).get("token") or data.get("token") or ""
        print(f"refresh 成功，新 accessToken = {token}")
        print(f"MQTT 用户名=MOBILE_{args.user_id}，密码=上面的 accessToken，地址={mqtt_host}")
        return 0

    subject = f"C=CN, CN=MOBILE_{args.user_id}_{int(time.time() * 1000)}"
    print(f"生成 CSR，subject={subject}")
    csr_pem, key_pem = gen_csr(subject)
    p10 = csr_to_p10(csr_pem)
    print(f"p10 长度={len(p10)}")

    data = signin(base, args.user_id, args.vin, sms_code, p10, session)
    if not is_success(data):
        print(f"signin 失败：{json.dumps(data, ensure_ascii=False)}", file=sys.stderr)
        return 5

    payload = data.get("data") or {}
    certificate = payload.get("certificate") or payload.get("certWithNewline") or ""
    token = payload.get("token") or ""
    if not certificate:
        print(f"响应中未找到 certificate：{json.dumps(data, ensure_ascii=False)}", file=sys.stderr)
        return 6

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    crt_path = out / f"{args.user_id}.crt"
    key_path = out / f"{args.user_id}.key"
    crt_path.write_text(wrap_pem_certificate(certificate))
    key_path.write_text(key_pem)
    print(f"证书已保存：{crt_path}")
    print(f"私钥已保存：{key_path}")

    print("\nMQTT 连接参数（HA 集成 / 探针脚本使用）：")
    print(f"  host     = {mqtt_host}")
    print(f"  clientId = {args.vin}-{args.user_id}-<任意IMEI串>")
    print(f"  username = MOBILE_{args.user_id}")
    print(f"  password = {token or '<signin 响应中的 accessToken>'}")
    print(f"  certfile = {crt_path}")
    print(f"  keyfile  = {key_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
