#!/usr/bin/env python3
"""ARCFOX token sync: phone App -> Home Assistant.

Reads the latest Control SDK log from a logged-in ARCFOX phone over adb,
extracts the currently valid ``appToken`` / ``imei`` / ``aid`` / ``vin``, and
updates the matching ``arcfox`` config entry in Home Assistant.

The phone only needs USB debugging.  No root, no captcha, no password.  The
vehicle read/control channel authenticates with the SDK ``appToken`` (32-hex
UUID from ``appToken:`` in ``control_sdk_log``) plus ``imei`` + ``aid`` + ``vin``;
the short-lived mg.arcfox.cn ``access_token`` is *not* needed for this path.

Usage:
    python3 tools/arcfox_sync.py --serial <adb-serial>
    python3 tools/arcfox_sync.py --serial <adb-serial> --restart

HA access is optional and only used when ``--apply`` is given:
    python3 tools/arcfox_sync.py --serial <adb-serial> --apply \\
        --ha-host <ha-host> --ha-ssh-port 22222 --ha-user root \\
        --ha-password '***' --restart
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ADB_CONTROL_LOG_DIR = "/sdcard/Android/data/com.bjev.arcfox/files/control_sdk_log"
HA_CONFIG_ENTRIES = "/mnt/data/supervisor/homeassistant/.storage/core.config_entries"

APP_TOKEN_RE = re.compile(r"appToken:([0-9a-fA-F]{32})")
IMEI_RE = re.compile(r"imei:([0-9a-zA-Z]{10,20})")
AID_RE = re.compile(r"AID:(\d+)")
VIN_RE = re.compile(r"vin:([A-HJ-NPR-Z0-9]{17})", re.IGNORECASE)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True)
    if check and proc.returncode != 0:
        raise SystemExit(
            f"命令失败({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc


def adb_devices() -> list[str]:
    out = run(["adb", "devices"]).stdout.decode("utf-8", "replace")
    serials: list[str] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line and "\tdevice" in line:
            serials.append(line.split()[0])
    return serials


def pick_serial(requested: str | None) -> str:
    serials = adb_devices()
    if not serials:
        raise SystemExit("未发现已授权的 adb 设备。请连接手机并开启 USB 调试。")
    if requested:
        if requested not in serials:
            raise SystemExit(f"指定设备 {requested} 未连接，当前设备: {serials}")
        return requested
    physical = [s for s in serials if not s.startswith("emulator-")]
    return (physical or serials)[0]


def latest_log(serial: str) -> tuple[str, str]:
    ls = run(["adb", "-s", serial, "shell", "ls", "-1t", ADB_CONTROL_LOG_DIR])
    names = [ln.strip() for ln in ls.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    names = [n for n in names if not n.endswith(":")]
    if not names:
        raise SystemExit(f"手机 {serial} 上没有 control_sdk_log，请先登录 App 并进入一次车辆控制页。")
    for name in names:
        path = f"{ADB_CONTROL_LOG_DIR}/{name}"
        cat = run(["adb", "-s", serial, "exec-out", "cat", path])
        text = cat.stdout.decode("utf-8", "replace")
        if APP_TOKEN_RE.search(text):
            return path, text
    raise SystemExit("日志里没有 appToken，请确认手机 App 已登录并进入过车辆控制页。")


def extract_credentials(text: str) -> dict[str, str]:
    def last(pattern: re.Pattern[str]) -> str:
        matches = pattern.findall(text)
        return matches[-1] if matches else ""

    vin = last(VIN_RE).upper()
    imei = last(IMEI_RE)
    aid = last(AID_RE)
    app_token = last(APP_TOKEN_RE).lower()
    return {"vin": vin, "imei": imei, "aid": aid, "app_token": app_token}


def mask(value: str, keep: int = 6) -> str:
    if not value:
        return "(空)"
    if len(value) <= keep * 2:
        return value
    return f"{value[:keep]}…{value[-keep:]}"


def validate_credentials(cred: dict[str, str], timeout: int) -> None:
    """Quick IOv handshake to confirm the appToken/imei/aid triple is accepted."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "arcfox_iov", str(Path(__file__).resolve().parents[1] / "custom_components/arcfox/iov.py")
    )
    iov = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(iov)

    client = iov.ArcfoxIovClient(
        vin=cred["vin"],
        access_token="sync-validate",
        aid=cred["aid"],
        imei=cred["imei"],
        remote_token=cred["app_token"],
        timeout=timeout,
    )
    try:
        client.connect()
        print("  ✓ IOv 握手成功（appToken/imei/aid 有效）")
    finally:
        try:
            client.close()
        except Exception:
            pass


def update_config_entries(payload: dict, cred: dict[str, str]) -> bool:
    found = False
    for entry in payload.get("data", {}).get("entries", []):
        if entry.get("domain") != "arcfox":
            continue
        data = entry.setdefault("data", {})
        options = entry.setdefault("options", {})
        data["imei"] = cred["imei"]
        data["remote_token"] = cred["app_token"]
        if cred["aid"]:
            data["aid"] = cred["aid"]
        if cred["vin"]:
            data["vin"] = cred["vin"]
        options["app_token"] = cred["app_token"]
        found = True
        print(f"  ✓ 已更新 entry {entry.get('entry_id')} ({entry.get('title')})")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--no-validate", action="store_true", help="跳过 IOv 握手校验")
    parser.add_argument("--out", help="只把更新后的 core.config_entries 写到该文件")
    parser.add_argument("--apply", action="store_true", help="通过 SSH 写回 HA 并备份")
    parser.add_argument("--restart", action="store_true", help="写回后重启 homeassistant")
    parser.add_argument("--ha-host", default="")
    parser.add_argument("--ha-ssh-port", type=int, default=22222)
    parser.add_argument("--ha-user", default="root")
    parser.add_argument("--ha-password", default="")
    args = parser.parse_args()
    if args.apply and not args.ha_host:
        parser.error("--apply 需要 --ha-host")

    serial = pick_serial(args.serial)
    path, text = latest_log(serial)
    cred = extract_credentials(text)
    if not all([cred["app_token"], cred["vin"], cred["imei"], cred["aid"]]):
        raise SystemExit(
            "日志信息不完整："
            f"vin={mask(cred['vin'])} imei={mask(cred['imei'])} "
            f"aid={cred['aid']} appToken={mask(cred['app_token'])}"
        )

    print(f"设备: {serial}")
    print(f"日志: {path}")
    print(f"  vin      = {cred['vin']}")
    print(f"  imei     = {mask(cred['imei'])}")
    print(f"  aid      = {cred['aid']}")
    print(f"  appToken = {mask(cred['app_token'])}")

    if not args.no_validate:
        try:
            validate_credentials(cred, args.timeout)
        except Exception as exc:
            print(f"  ⚠ 握手校验失败：{type(exc).__name__} {str(exc)[:120]}")
            if not args.apply:
                print("    继续输出 JSON（车辆可能休眠/网络波动，稍后可重试）。")

    payload = {
        "version": 1,
        "minor_version": 5,
        "key": "core.config_entries",
        "data": {"entries": []},
    }
    out_path = args.out
    if args.apply or out_path:
        # Start from the live HA file when applying, otherwise from an empty
        # template (caller supplies --out for a full copy they prepared).
        if args.apply:
            payload = json.loads(
                subprocess.run(
                    [
                        "sshpass", "-p", args.ha_password,
                        "ssh", "-p", str(args.ha_ssh_port),
                        "-o", "StrictHostKeyChecking=no",
                        f"{args.ha_user}@{args.ha_host}",
                        f"cat {HA_CONFIG_ENTRIES}",
                    ],
                    capture_output=True, check=True,
                ).stdout.decode("utf-8")
            )
        if not update_config_entries(payload, cred):
            raise SystemExit("HA core.config_entries 中没有 arcfox 条目。")
        updated = json.dumps(payload, ensure_ascii=False, indent=2)
        if out_path:
            Path(out_path).write_text(updated, encoding="utf-8")
            print(f"已写入 {out_path}")
        else:
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8"
            )
            tmp.write(updated)
            tmp.close()
            remote = HA_CONFIG_ENTRIES
            backup = f"{remote}.bak_arcfox_{int(time.time())}"
            ssh_base = [
                "sshpass", "-p", args.ha_password,
                "ssh", "-p", str(args.ha_ssh_port),
                "-o", "StrictHostKeyChecking=no",
                f"{args.ha_user}@{args.ha_host}",
            ]
            scp_base = [
                "sshpass", "-p", args.ha_password,
                "scp", "-P", str(args.ha_ssh_port),
                "-o", "StrictHostKeyChecking=no",
            ]
            run(ssh_base + [f"cp {remote} {backup}"])
            print(f"  ✓ HA 已备份为 {backup}")
            run(scp_base + [tmp.name, f"{args.ha_user}@{args.ha_host}:{remote}"])
            print(f"  ✓ 已写回 {remote}")
            if args.restart:
                run(ssh_base + ["docker restart homeassistant"])
                print("  ✓ 已重启 homeassistant")
    else:
        print("\n当前只做提取/校验。要写回 HA 请加 --apply 并给 --ha-password。")
        print(f"appToken={cred['app_token']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
