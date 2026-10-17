#!/usr/bin/env python3
"""ARCFOX mg.arcfox.cn login helper.

Implements the real ARCFOX account login used by the current app:

    getVerifyCodeNew (SMS)  ->  loginByMobile (SMS code)
    specialLogin            ->  password login

All requests are signed with the Java fallback signature that the official
app uses when its native signature library is unavailable.  The signer has
been verified byte-for-byte against a live app capture.

The login endpoint requires an Aliyun geetest v4 captcha.  Solve it with
``captcha.html`` and pass the resulting JSON via ``--captcha``.

Usage:
    # 1. solve captcha -> save JSON to captcha.json
    python3 arcfox_mg_login.py --phone 1xxxxxxxxxx --captcha captcha.json \
        --sms-code 123456
    python3 arcfox_mg_login.py --phone 1xxxxxxxxxx --captcha captcha.json \
        --password 'your-password'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
import uuid

MG_BASE = "https://mg.arcfox.cn/"
APP_KEY = "2368392532"
SECRET_KEY = "26abfc143bfe3cda422d91e4c9ca4783"
APP_VERSION = "3.4.28"
APP_CODE = "325"
CAPTCHA_ID = "648f556d858f24ee0b13c6e66a12a62e"


def sign(path: str, params: dict[str, str]) -> str:
    """Reproduce RequestUtils.getQueryParams / sign_core::sign (Java fallback)."""
    ordered = "".join(f"{k}={v}_" for k, v in sorted(params.items()))
    raw = f"{path}_{ordered}{SECRET_KEY}"
    encoded = urllib.parse.quote(raw, safe="")
    return hashlib.md5(encoded.encode("utf-8")).hexdigest().lower()


def signed_url(path: str, extra: dict[str, str]) -> str:
    params = {
        "appkey": APP_KEY,
        "signt": str(int(time.time() * 1000)),
        "nonce": str(uuid.uuid4()),
    }
    params.update(extra)
    params["sign"] = sign(path, params)
    return MG_BASE + path + "?" + urllib.parse.urlencode(params)


def request(path: str, body: dict, extra_query: dict[str, str] | None = None,
            phone: str = "", aid: str = "", imei: str = "") -> dict:
    url = signed_url(path, extra_query or {})
    headers = {
        "User-Agent": "okhttp/4.9.1",
        "Content-Type": "application/json",
        "platform": "Android",
        "appversion": APP_VERSION,
        "appcode": APP_CODE,
        "deviceModel": "sdk_gphone64_x86_64",
    }
    if aid:
        headers["aid"] = aid
    if imei:
        headers["deviceId"] = imei
    if phone:
        headers["mobile"] = phone
    data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        return json.loads(err.read().decode("utf-8", "replace"))


def load_captcha(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        value = json.load(fh)
    keys = ("lot_number", "captcha_output", "pass_token", "gen_time")
    if not all(k in value for k in keys):
        raise SystemExit("captcha JSON 缺少字段，需要: " + ", ".join(keys))
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", required=True)
    parser.add_argument("--captcha", help="captcha.html 输出的 JSON 文件")
    parser.add_argument("--sms-code")
    parser.add_argument("--password")
    parser.add_argument("--aid", default="")
    parser.add_argument("--imei", default="")
    args = parser.parse_args()

    captcha = load_captcha(args.captcha) if args.captcha else {}
    device = {
        "deviceBrand": "google",
        "deviceModel": "sdk_gphone64_x86_64",
        "deviceId": args.imei or "000000000000000",
    }

    if args.sms_code:
        login_path = "user/public/login/loginByMobile"
        login_body = {
            "mobile": args.phone,
            "verifyCode": args.sms_code,
            "province": "北京市",
            "city": "北京市",
            "provinceCode": "110000",
            "cityCode": "110100",
            **device,
        }
    elif args.password:
        login_path = "user/public/login/specialLogin"
        login_body = {
            "username": args.phone,
            "password": args.password,
            "clientType": "APP",
            **device,
            **captcha,
        }
    else:
        raise SystemExit("需要 --sms-code 或 --password")

    if not captcha and args.sms_code:
        # SMS code path: captcha is needed to *send* the code, so require it up front.
        raise SystemExit("短信登录需要 --captcha（先打开 captcha.html 完成验证）")

    if captcha and args.sms_code:
        verify_path = "user/public/verifyCode/getVerifyCodeNew"
        verify_body = {
            "mobile": args.phone,
            "verifyCodeUseFlag": "LOGIN",
            "lotNumber": captcha.get("lot_number"),
            "captchaOutput": captcha.get("captcha_output"),
            "passToken": captcha.get("pass_token"),
            "genTime": captcha.get("gen_time"),
        }
        print("== 请求短信验证码 ==")
        print(json.dumps(request(verify_path, verify_body, phone=args.phone,
                                 aid=args.aid, imei=args.imei), ensure_ascii=False))

    print(f"== 登录 {login_path} ==")
    result = request(login_path, login_body, phone=args.phone,
                     aid=args.aid, imei=args.imei)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("status") == "SUCCEED" and result.get("data"):
        data = result["data"]
        print("\n== 登录成功，保存以下值 ==")
        print("access_token =", data.get("token"))
        print("tsp_uid      =", data.get("tspUid"))
        print("car_token    =", data.get("carToken"))
        account = data.get("accountVo") or {}
        print("aid          =", account.get("aid"))


if __name__ == "__main__":
    main()
