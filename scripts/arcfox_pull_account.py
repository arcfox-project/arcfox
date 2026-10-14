#!/usr/bin/env python3
"""从已登录的极狐 App 日志中提取车控账号信息（AID / userId / VIN）。

手机连 USB（开启 USB 调试）并登录 App、进入“车辆控制页”后运行本脚本。
只读：仅执行 ``adb shell ls`` / ``adb exec-out cat``，不会启动 App 或下发指令。

提取目标：
* control_sdk_log 里的 ``AID:xxxxx``（车控 userId 大概率就是它）
* 更权威的 ``Mqtt==>init:vin=... userid=...``（SDK 自己的 .dat 日志）
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

CONTROL_LOG_DIR = "/sdcard/Android/data/com.bjev.arcfox/files/control_sdk_log"
SDK_CACHE_DIR = "/sdcard/Android/data/com.bjev.arcfox/cache/log"

AID_RE = re.compile(r"AID:(\d+)")
APPTOKEN_RE = re.compile(r"appToken:([0-9a-fA-F]+)")
IMEI_RE = re.compile(r"imei:([0-9a-zA-Z]+)")
VIN_RE = re.compile(r"vin:([A-HJ-NPR-Z0-9]{17})", re.IGNORECASE)
USERID_RE = re.compile(r"(?:userid|userId|user_id)\s*[=:：]\s*([0-9A-Za-z_-]+)", re.IGNORECASE)


def _run(cmd: list[str]) -> bytes:
    try:
        proc = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"找不到 adb：{exc.filename}（请安装 Android platform-tools 或指定 --adb）") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"adb 失败（{proc.returncode}）：{stderr}")
    return proc.stdout


def _adb_base(adb: str, serial: str | None) -> list[str]:
    base = [adb]
    if serial:
        base += ["-s", serial]
    return base


def _ls(base: list[str], path: str) -> list[str]:
    out = _run(base + ["shell", "ls", "-1t", path])
    lines = [ln.strip() for ln in out.decode("utf-8", "replace").splitlines() if ln.strip()]
    return [ln for ln in lines if not ln.endswith(":")]


def _cat(base: list[str], path: str) -> str:
    return _run(base + ["exec-out", "cat", path]).decode("utf-8", "replace")


def _grab(paths: list[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {"AID": set(), "appToken": set(), "imei": set(), "vin": set(), "userId": set()}
    for path in paths:
        text = _cat(adb_base_local, path)
        found["AID"].update(AID_RE.findall(text))
        found["appToken"].update(APPTOKEN_RE.findall(text))
        found["imei"].update(IMEI_RE.findall(text))
        found["vin"].update(m.upper() for m in VIN_RE.findall(text))
        found["userId"].update(USERID_RE.findall(text))
    return found


def main() -> int:
    global adb_base_local
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    args = parser.parse_args()

    base = _adb_base(args.adb, args.serial)
    adb_base_local = base

    # 1) 设备检查
    devices = _run([args.adb, "devices"]).decode("utf-8", "replace")
    attached = [ln for ln in devices.splitlines()[1:] if ln.strip() and "\tdevice" in ln]
    if not attached:
        print("未检测到已授权的 adb 设备。请插 USB、开启 USB 调试并在手机上允许调试。", file=sys.stderr)
        return 2
    print("设备：", [ln.split()[0] for ln in attached])

    # 2) control_sdk_log 最新文件（App 层日志，含 AID）
    paths: list[str] = []
    try:
        for name in _ls(base, CONTROL_LOG_DIR):
            if name.endswith(".text") or name.endswith(".log") or name.endswith(".dat"):
                paths.append(f"{CONTROL_LOG_DIR}/{name}")
            if len(paths) >= 3:
                break
    except SystemExit:
        print(f"无法读取 {CONTROL_LOG_DIR}（Android 11+ 可能受限）。", file=sys.stderr)

    # 3) SDK .dat 日志（含 Mqtt==>init:vin=...userid=...）
    try:
        day_dirs = _ls(base, SDK_CACHE_DIR)
        for day in day_dirs[:2]:
            for name in _ls(base, f"{SDK_CACHE_DIR}/{day}"):
                if name.endswith(".dat"):
                    paths.append(f"{SDK_CACHE_DIR}/{day}/{name}")
                if len(paths) >= 8:
                    break
    except SystemExit:
        pass

    if not paths:
        print("没有找到任何日志文件。请先登录 App 并进入车辆控制页。", file=sys.stderr)
        return 3

    found = _grab(paths)
    for key, values in found.items():
        if values:
            print(f"{key}: {', '.join(sorted(values))}")
    if not any(found.values()):
        print("日志里没找到账号信息。请确认已登录新账号并进入过车辆控制页。", file=sys.stderr)
        return 4

    print("\n拿到 AID 后，用它替换下面的 <AID> 跑证书脚本：")
    print("  python3 scripts/arcfox_bootstrap_cert.py --user-id <AID> --vin <VIN> --model be12")
    return 0


adb_base_local: list[str] = []


if __name__ == "__main__":
    raise SystemExit(main())
