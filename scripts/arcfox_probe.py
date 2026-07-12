#!/usr/bin/env python3
"""Probe ARCFOX read-only vehicle endpoints outside Home Assistant."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "custom_components" / "arcfox" / "certs"

BASE_URLS = (
    "https://sdkserver-be12.bjev.com.cn/api",
    "https://sdkserver-be12-pub.bjev.com.cn/api",
    "https://sdkserver-n5.bjev.com.cn/api",
    "https://sdkserver-n80.bjev.com.cn/api",
    "https://sdkserver.bjev.com.cn/api",
    "https://hbt-app-rsa.bjev.com.cn",
    "https://hbt-app-rsa.bjev.com.cn/api",
    "https://napi.arcfox.cn",
    "https://napi.arcfox.cn/api",
    "https://mg.arcfox.cn",
    "https://mg.arcfox.cn/api",
    "https://arcfoxapp-new-iov.bjev.com.cn",
    "https://arcfoxapp-new-iov.bjev.com.cn/api",
)

B2C_LOGIN_PATH = "/vcam/v1/auth/accounts/login"
B2C_ACCOUNT_BASE_PATH = "/vcam/v1/accounts/base"
B2C_VEHICLE_INFO_PATHS = (
    "/vcam/v1/accounts/vehicles/{vehicle_id}",
    "/vcam/v1/accounts/vehicle-infos/{vehicle_id}",
    "/vcam/v1/vehicle-infos/{vehicle_id}",
)
B2C_DYNAMIC_INFO_PATH = "/vctrl/v2/controls/dynamic-infos"

CAR_STATUS_QUERY_KEYS = (
    "gps,kmTotal,limitedDriving,current,chargingleft,soc,insideTemperature,"
    "chrgDchaPwrDisp,InsdPM25DataDisp,status.statusDataSendTime,status.S3,"
    "status.S4,status.S9,status.S10,status.S16,status.S22,status.S27,status.S30,"
    "status.S32,status.S33,status.S34,status.S37,status.S38,status.S39,status.S41,"
    "status.S42,status.S43,status.S44,status.S45,status.S46,status.S47,status.S48,"
    "status.S49,status.S50,status.S51,status.S52,status.S53,status.S61,status.S62,"
    "status.S63,status.S65,status.S66,status.S67,status.S71,status.S73,status.S74,"
    "status.S75,status.S76,status.S77,status.S80,status.S82,status.S83,status.S84,"
    "status.S85,status.S86,status.S87,status.S88,status.S89,status.S90,status.S91,"
    "status.S92,status.S93,status.S94,status.S95,status.S96,status.S97,status.S98,"
    "status.S99,status.S100,status.S101,status.S102,status.S103,status.S105,"
    "status.S106,status.S107,status.S108,status.S109,status.S112,status.S116,"
    "status.S121,status.S125,status.S126,status.S128,status.S134,status.S135,"
    "status.S136,status.S147limitedDriving,fuelSoc,fuelMilge,fuelMilgVld,"
    "evMilgVld,soc,status.S140,status.S138,status.S139,status.S141,status.S142,"
    "status.S143,status.S144,status.S145,status.S155,status.S149,status.S150,"
    "status.S153,status.S166"
)

STATUS_KEYS = {
    "soc",
    "SOC",
    "chargeLeft",
    "chargingleft",
    "limitedDriving",
    "current",
    "kmTotal",
    "mileage",
    "totalMileage",
    "vcuSumRemainingMileage",
    "vcuWltcRemainingMileage",
    "vcuNedcRemainingMileage",
    "vcuCltcRemainingMileage",
}


def build_ssl_context(url: str) -> ssl.SSLContext | None:
    if ".bjev.com.cn" not in url:
        return None

    ca_path = CERT_DIR / "baic_root_ca.pem"
    client_cert_path = CERT_DIR / "baic_https_client.pem"
    client_key_path = CERT_DIR / "baic_https_client_key.pem"
    if not ca_path.exists():
        return None

    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(ca_path))
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    if client_cert_path.exists() and client_key_path.exists():
        context.load_cert_chain(
            certfile=str(client_cert_path),
            keyfile=str(client_key_path),
        )
    return context


def build_headers(
    token: str,
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "X-Nonce": str(uuid.uuid4()),
        "X-Client-Version": "3.4.28",
        "User-Agent": "ARCFOX/3.4.28 Android",
    }
    if token:
        headers.update(
            {
                "Authorization": token,
                "accessToken": token,
                "token": token,
                "X-Access-Token": token,
            }
        )
    if extra_headers:
        headers.update(extra_headers)
    return headers


def request_json(
    url: str,
    token: str,
    timeout: int,
    *,
    method: str = "GET",
    json_payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int | None, Any, str]:
    data = None
    headers = build_headers(token, extra_headers=extra_headers)
    if json_payload is not None:
        data = json.dumps(json_payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, headers=headers, data=data, method=method)
    try:
        with urlopen(request, timeout=timeout, context=build_ssl_context(url)) as response:
            body = response.read()
            status = response.status
    except HTTPError as err:
        body = err.read()
        status = err.code
    except (TimeoutError, URLError, OSError) as err:
        return None, None, str(err)

    text = body.decode("utf-8", "replace")
    try:
        return status, json.loads(text), text[:500]
    except json.JSONDecodeError:
        return status, None, text[:500]


def walk_values(payload: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in STATUS_KEYS and item not in (None, ""):
                    found.setdefault(key, item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return found


def compact_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        keys = list(payload.keys())[:20]
        code = payload.get("code")
        success = payload.get("success")
        message = payload.get("message") or payload.get("msg")
        return f"keys={keys} code={code!r} success={success!r} message={message!r}"
    if isinstance(payload, list):
        return f"list len={len(payload)}"
    return "non-json"


def extract_token(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.insert(0, data)
    for candidate in candidates:
        token = (
            candidate.get("token")
            or candidate.get("accessToken")
            or candidate.get("access_token")
        )
        if token:
            return str(token)
    return None


def extract_refresh_token(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.insert(0, data)
    for candidate in candidates:
        refresh_token = (
            candidate.get("refreshToken")
            or candidate.get("refresh_token")
            or candidate.get("requestRefreshToken")
        )
        if refresh_token:
            return str(refresh_token)
    return None


def extract_account_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.insert(0, data)
    for candidate in candidates:
        account_id = (
            candidate.get("accountId")
            or candidate.get("account_id")
            or candidate.get("userId")
        )
        if account_id:
            return str(account_id)
    return None


def b2c_login(
    base_urls: list[str],
    account: str,
    password: str,
    timeout: int,
    *,
    code: str | None = None,
    app_token: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    payload: dict[str, Any] = {
        "method": "password",
        "passwordCredential": {
            "account": account,
            "password": password,
        },
        "device": {
            "id": "codex-probe",
            "model": "Codex Probe",
            "type": 1,
        },
    }
    if code:
        payload["passwordCredential"]["code"] = code

    for base_url in base_urls:
        url = f"{base_url.rstrip('/')}{B2C_LOGIN_PATH}"
        headers_token = app_token or ""
        status, response, detail = request_json(
            url,
            headers_token,
            timeout,
            method="POST",
            json_payload=payload,
        )
        if status is None:
            print(f"ERR  {url} :: {detail}")
            continue
        print(f"{status:<4} {url} :: {compact_payload(response)}")
        token = extract_token(response)
        refresh_token = extract_refresh_token(response)
        account_id = extract_account_id(response)
        if token:
            print(f"     access_token={token[:12]}...{token[-8:]}")
            if refresh_token:
                print(f"     refresh_token={refresh_token[:12]}...{refresh_token[-8:]}")
            if account_id:
                print(f"     account_id={account_id}")
            return token, refresh_token, account_id
        if status and status < 400 and detail:
            print(f"     body={detail[:240].replace(chr(10), ' ')}")
    return None, None, None


def b2c_account_base(
    base_urls: list[str],
    token: str,
    timeout: int,
) -> str | None:
    for base_url in base_urls:
        url = f"{base_url.rstrip('/')}{B2C_ACCOUNT_BASE_PATH}"
        status, response, detail = request_json(url, token, timeout)
        if status is None:
            print(f"ERR  {url} :: {detail}")
            continue
        print(f"{status:<4} {url} :: {compact_payload(response)}")
        account_id = extract_account_id(response)
        if account_id:
            print(f"     account_id={account_id}")
            return account_id
        if status and status < 400 and detail:
            print(f"     body={detail[:240].replace(chr(10), ' ')}")
    return None


def b2c_vehicle_info(
    base_urls: list[str],
    token: str,
    vehicle_id: str,
    timeout: int,
) -> None:
    for base_url in base_urls:
        for path in B2C_VEHICLE_INFO_PATHS:
            url = f"{base_url.rstrip('/')}{path.format(vehicle_id=quote(vehicle_id, safe=''))}"
            status, response, detail = request_json(url, token, timeout)
            if status is None:
                print(f"ERR  {url} :: {detail}")
                continue
            values = walk_values(response)
            print(f"{status:<4} {url} :: {compact_payload(response)}")
            if values:
                print(f"     values={json.dumps(values, ensure_ascii=False)}")
            elif status and status < 400 and detail:
                print(f"     body={detail[:240].replace(chr(10), ' ')}")


def b2c_dynamic_info(
    base_urls: list[str],
    token: str,
    vehicle_id: str,
    timeout: int,
) -> None:
    payloads = [
        {
            "vehicleStatus": "",
            "charge": "",
            "location": "",
            "door": "",
            "window": "",
            "seat": "",
            "hvac": "",
            "lamp": "",
            "fuel": "",
            "airConditionPlan": "",
            "departurePlan": "",
            "sentryPlan": "",
            "tire": "",
            "warmCoolingBox": "",
            "welcome": "",
        },
        {
            "vehicleStatus": "1",
            "charge": "1",
            "location": "1",
            "door": "1",
            "window": "1",
            "seat": "1",
            "hvac": "1",
            "lamp": "1",
            "fuel": "1",
            "airConditionPlan": "1",
            "departurePlan": "1",
            "sentryPlan": "1",
            "tire": "1",
            "warmCoolingBox": "1",
            "welcome": "1",
        },
    ]

    for base_url in base_urls:
        url = f"{base_url.rstrip('/')}{B2C_DYNAMIC_INFO_PATH}"
        for payload in payloads:
            status, response, detail = request_json(
                url,
                token,
                timeout,
                method="POST",
                json_payload=payload,
                extra_headers={
                    "X-Vehicle-Id": vehicle_id,
                    "token_type": "user_token",
                },
            )
            if status is None:
                print(f"ERR  {url} :: {detail}")
                continue
            values = walk_values(response)
            print(f"{status:<4} {url} :: payload_keys={sorted(payload.keys())} {compact_payload(response)}")
            if values:
                print(f"     values={json.dumps(values, ensure_ascii=False)}")
            elif status and status < 400 and detail:
                print(f"     body={detail[:240].replace(chr(10), ' ')}")


def b2c_energy(
    base_urls: list[str],
    token: str,
    vehicle_id: str,
    timeout: int,
) -> None:
    paths = (
        "/vdas/v1/report/energy/latest",
        "/vdas/v1/report/energy/account/latest",
    )
    for base_url in base_urls:
        for path in paths:
            url = f"{base_url.rstrip('/')}{path}"
            status, response, detail = request_json(
                url,
                token,
                timeout,
                extra_headers={
                    "X-Vehicle-Id": vehicle_id,
                    "token_type": "user_token",
                },
            )
            if status is None:
                print(f"ERR  {url} :: {detail}")
                continue
            values = walk_values(response)
            print(f"{status:<4} {url} :: {compact_payload(response)}")
            if values:
                print(f"     values={json.dumps(values, ensure_ascii=False)}")
            elif status and status < 400 and detail:
                print(f"     body={detail[:240].replace(chr(10), ' ')}")


def generate_csr(user_id: str) -> str:
    """Generate a PKCS#10 CSR and return the base64 body expected by the SDK."""
    subject = f"/C=CN/CN=MOBILE_{user_id}_{int(time.time() * 1000)}"
    with tempfile.TemporaryDirectory(prefix="arcfox-csr-") as tmp_dir:
        key_path = Path(tmp_dir) / "mobile.key"
        csr_path = Path(tmp_dir) / "mobile.csr"
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key_path),
                "-out",
                str(csr_path),
                "-subj",
                subject,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        csr_text = csr_path.read_text(encoding="utf-8")
    return (
        csr_text.replace("-----BEGIN CERTIFICATE REQUEST-----", "")
        .replace("-----END CERTIFICATE REQUEST-----", "")
        .replace("\r", "")
        .replace("\n", "")
        .replace(" ", "")
    )


def request_sms_code(base_urls: list[str], user_id: str, vin: str, timeout: int) -> bool:
    payload = {"userId": user_id, "vin": vin}
    for base_url in base_urls:
        url = f"{base_url.rstrip('/')}/auth/signinsms"
        status, response, detail = request_json(url, "", timeout, method="POST", json_payload=payload)
        if status is None:
            print(f"ERR  {url} :: {detail}")
            continue
        print(f"{status:<4} {url} :: {compact_payload(response)}")
        if status and status < 400 and isinstance(response, dict):
            code = response.get("code")
            success = response.get("success")
            if success is not False and code in (0, 200, "0", "200", None):
                return True
    return False


def signin_with_sms_code(
    base_urls: list[str],
    user_id: str,
    vin: str,
    sms_code: str,
    timeout: int,
) -> str | None:
    p10 = generate_csr(user_id)
    payload = {"userId": user_id, "vin": vin, "smsCode": sms_code, "p10": p10}
    for base_url in base_urls:
        url = f"{base_url.rstrip('/')}/auth/signin"
        status, response, detail = request_json(url, "", timeout, method="POST", json_payload=payload)
        if status is None:
            print(f"ERR  {url} :: {detail}")
            continue
        print(f"{status:<4} {url} :: {compact_payload(response)}")
        token = extract_token(response)
        refresh_token = extract_refresh_token(response)
        if token:
            print(f"     access_token={token[:12]}...{token[-8:]}")
            if refresh_token:
                print(f"     refresh_token={refresh_token[:12]}...{refresh_token[-8:]}")
            return token
        if status and status < 400 and detail:
            print(f"     body={detail[:240].replace(chr(10), ' ')}")
    return None


def refresh_access_token(base_urls: list[str], vin: str, refresh_token: str, timeout: int) -> str | None:
    for base_url in base_urls:
        url = f"{base_url.rstrip('/')}/auth/refreshtoken"
        status, payload, detail = request_json(
            url,
            "",
            timeout,
            method="POST",
            json_payload={"vin": vin, "refreshToken": refresh_token},
        )
        if status is None:
            print(f"ERR  {url} :: {detail}")
            continue
        summary = compact_payload(payload)
        print(f"{status:<4} {url} :: {summary}")
        token = extract_token(payload)
        if token:
            print(f"     refreshed_access_token={token[:12]}...{token[-8:]}")
            return token
    return None


def endpoint_paths(vin: str, user_id: str | None) -> list[str]:
    quoted_vin = quote(vin, safe="")
    paths = [
        f"/tsp/car/vehicleConfig/{quoted_vin}",
        f"/rc/bctp/carState/query/{quoted_vin}?queryKeys={quote(CAR_STATUS_QUERY_KEYS, safe=',.')}",
        f"/rc/battery/info/{quoted_vin}",
        f"/rc/battery/info?vehicleId={quoted_vin}",
    ]
    if user_id:
        quoted_user_id = quote(user_id, safe="")
        paths.insert(0, f"/tsp/userAccount/findBindUserList/{quoted_user_id}")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vin", default=os.getenv("ARCFOX_VIN"), required=not os.getenv("ARCFOX_VIN"))
    parser.add_argument("--token", default=os.getenv("ARCFOX_TOKEN"))
    parser.add_argument("--refresh-token", default=os.getenv("ARCFOX_REFRESH_TOKEN"))
    parser.add_argument("--user-id", default=os.getenv("ARCFOX_USER_ID"))
    parser.add_argument("--vehicle-id", default=os.getenv("ARCFOX_VEHICLE_ID"))
    parser.add_argument("--account", default=os.getenv("ARCFOX_ACCOUNT"))
    parser.add_argument("--password", default=os.getenv("ARCFOX_PASSWORD"))
    parser.add_argument("--code", default=os.getenv("ARCFOX_CODE"))
    parser.add_argument("--app-token", default=os.getenv("ARCFOX_APP_TOKEN"))
    parser.add_argument("--b2c-login", action="store_true", help="probe /vcam/v1/auth/accounts/login first")
    parser.add_argument("--b2c-vehicle-info", action="store_true", help="probe B2C vehicle info endpoints with --vehicle-id")
    parser.add_argument("--b2c-dynamic-info", action="store_true", help="probe experimental /vctrl/v2/controls/dynamic-infos with --vehicle-id")
    parser.add_argument("--b2c-energy", action="store_true", help="probe /vdas/v1/report/energy/latest endpoints with --vehicle-id")
    parser.add_argument("--request-sms", action="store_true", help="request SDK SMS code then exit")
    parser.add_argument("--sms-code", default=os.getenv("ARCFOX_SMS_CODE"), help="SDK SMS code for /auth/signin")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--base-url", action="append", dest="base_urls")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_urls = args.base_urls or list(BASE_URLS)
    if args.b2c_login:
        if not args.account or not args.password:
            print("Missing account/password. Set ARCFOX_ACCOUNT and ARCFOX_PASSWORD.")
            return 2
        token, refresh_token, account_id = b2c_login(
            base_urls,
            args.account,
            args.password,
            args.timeout,
            code=args.code,
            app_token=args.app_token,
        )
        if not token:
            return 2
        if not account_id:
            account_id = b2c_account_base(base_urls, token, args.timeout)
        if account_id:
            print(f"\nresolved_account_id={account_id}")
        if refresh_token:
            print(f"resolved_refresh_token={refresh_token}")
        print(f"resolved_access_token={token}")
        return 0

    if args.request_sms:
        if not args.user_id:
            print("Missing user id. Set ARCFOX_USER_ID or --user-id.")
            return 2
        return 0 if request_sms_code(base_urls, args.user_id, args.vin, args.timeout) else 2

    token = args.token
    if not token and args.sms_code:
        if not args.user_id:
            print("Missing user id. Set ARCFOX_USER_ID or --user-id.")
            return 2
        token = signin_with_sms_code(base_urls, args.user_id, args.vin, args.sms_code, args.timeout)
    if not token and args.refresh_token:
        token = refresh_access_token(base_urls, args.vin, args.refresh_token, args.timeout)
    if not token:
        print("Missing token. Set ARCFOX_TOKEN or ARCFOX_REFRESH_TOKEN.")
        return 2

    if args.b2c_vehicle_info:
        if not args.vehicle_id:
            print("Missing vehicle id. Set ARCFOX_VEHICLE_ID or --vehicle-id.")
            return 2
        b2c_vehicle_info(base_urls, token, args.vehicle_id, args.timeout)
        return 0

    if args.b2c_dynamic_info:
        if not args.vehicle_id:
            print("Missing vehicle id. Set ARCFOX_VEHICLE_ID or --vehicle-id.")
            return 2
        b2c_dynamic_info(base_urls, token, args.vehicle_id, args.timeout)
        return 0

    if args.b2c_energy:
        if not args.vehicle_id:
            print("Missing vehicle id. Set ARCFOX_VEHICLE_ID or --vehicle-id.")
            return 2
        b2c_energy(base_urls, token, args.vehicle_id, args.timeout)
        return 0

    paths = endpoint_paths(args.vin, args.user_id)
    hits = 0

    for base_url in base_urls:
        for path in paths:
            url = f"{base_url.rstrip('/')}{path}"
            status, payload, detail = request_json(url, token, args.timeout)
            if status is None:
                print(f"ERR  {url} :: {detail}")
                continue

            summary = compact_payload(payload)
            values = walk_values(payload)
            print(f"{status:<4} {url} :: {summary}")
            if values:
                hits += 1
                print(f"     values={json.dumps(values, ensure_ascii=False)}")
            elif status and status < 400 and detail:
                print(f"     body={detail[:240].replace(chr(10), ' ')}")

    if hits:
        print(f"\nfound_status_payloads={hits}")
        return 0
    print("\nfound_status_payloads=0")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
