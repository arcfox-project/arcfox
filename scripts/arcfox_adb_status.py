#!/usr/bin/env python3
"""Read cached ARCFOX vehicle state from the official Android app's SDK log.

This helper is deliberately read-only.  It only runs ``adb shell ls`` and
``adb exec-out cat``; it never starts the app or sends a vehicle query.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


REMOTE_LOG_DIR = "/sdcard/Android/data/com.bjev.arcfox/files/control_sdk_log"
TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)")

# Only direct SDK-to-app state callbacks are parsed.  In particular, the
# duplicated "SDK log" callbacks can contain credentials and are ignored.
STATE_MARKERS = (
    "向APP反馈数据库车辆状态:",
    "向APP反馈车辆状态:",
    "向APP反馈主动上报车辆状态变化:",
    "向APP反馈主动上报停车时门窗状态上报:",
)

SAFE_FIELDS = {
    "airState",
    "airTemperature",
    "batteryTemperature",
    "chargeGunState",
    "chargeState",
    "currentBattery",
    "driveTemperature",
    "leftBackDoor",
    "leftFrontDoor",
    "lockState",
    "mileage",
    "rightBackDoor",
    "rightFrontDoor",
    "skylightState",
    "totalMileage",
    "trunkState",
    "windowClose",
    "windowState",
}


class StatusReadError(RuntimeError):
    """Raised when a cached status cannot be read."""


@dataclass
class ParsedState:
    """Merged safe vehicle state and its timestamps."""

    values: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime | None = None
    full_state_at: datetime | None = None
    records: int = 0


def _parse_timestamp(line: str) -> datetime | None:
    match = TIMESTAMP_RE.match(line)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_log(text: str) -> ParsedState:
    """Parse and chronologically merge safe fields from an SDK log."""
    result = ParsedState()

    for line in text.splitlines():
        marker = next((item for item in STATE_MARKERS if item in line), None)
        if marker is None:
            continue

        timestamp = _parse_timestamp(line)
        json_start = line.find("{", line.find(marker) + len(marker))
        if timestamp is None or json_start < 0:
            continue

        try:
            payload = json.loads(line[json_start:])
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(payload, dict) or payload.get("isSuccess") is False:
            continue
        state = payload.get("carControlStateBean")
        if not isinstance(state, dict):
            continue

        safe = {key: state[key] for key in SAFE_FIELDS if key in state}
        if not safe:
            continue

        result.values.update(safe)
        result.observed_at = max(result.observed_at or timestamp, timestamp)
        result.records += 1
        if "向APP反馈数据库车辆状态:" in line or len(safe) >= 10:
            result.full_state_at = max(result.full_state_at or timestamp, timestamp)

    if not result.values:
        raise StatusReadError("日志中没有找到可解析的车辆状态缓存")
    return result


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _code_is(value: Any, expected: str) -> bool | None:
    if value in (None, ""):
        return None
    return str(value) == expected


def _closed(value: Any) -> bool | None:
    """The G4 SDK uses 0 for a closed door/window and 1 for open."""
    return _code_is(value, "0")


def normalize_status(parsed: ParsedState) -> dict[str, Any]:
    """Return a secret-free, Home Assistant friendly status object."""
    state = parsed.values
    doors = {
        "front_left_closed": _closed(state.get("leftFrontDoor")),
        "front_right_closed": _closed(state.get("rightFrontDoor")),
        "rear_left_closed": _closed(state.get("leftBackDoor")),
        "rear_right_closed": _closed(state.get("rightBackDoor")),
        "trunk_closed": _closed(state.get("trunkState")),
    }

    return {
        "source": "arcfox_android_sdk_cache",
        "read_only": True,
        "observed_at": parsed.observed_at.isoformat() if parsed.observed_at else None,
        "full_state_at": (
            parsed.full_state_at.isoformat() if parsed.full_state_at else None
        ),
        "records_merged": parsed.records,
        "battery_pct": _as_float(state.get("currentBattery")),
        "range_km": _as_float(state.get("mileage")),
        "odometer_km": _as_float(state.get("totalMileage")),
        "climate_on": _code_is(state.get("airState"), "1"),
        "climate_target_c": _as_float(state.get("airTemperature")),
        "charging": _code_is(state.get("chargeState"), "2"),
        "doors": doors,
        "all_doors_closed": (
            all(doors.values()) if all(value is not None for value in doors.values()) else None
        ),
        "all_windows_closed": _closed(state.get("windowState")),
        "sunroof_closed": _closed(state.get("skylightState")),
        # The meaning of 0/1 differs between ARCFOX SDK generations.  Keep the
        # harmless raw code until it can be verified against the app UI.
        "lock_state_code": (
            str(state["lockState"]) if state.get("lockState") not in (None, "") else None
        ),
    }


def _adb_base(adb: str, serial: str | None) -> list[str]:
    command = [adb]
    if serial:
        command.extend(("-s", serial))
    return command


def _run_adb(command: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except FileNotFoundError as err:
        raise StatusReadError("找不到 adb，请用 --adb 指定路径") from err
    except subprocess.TimeoutExpired as err:
        raise StatusReadError("读取手机日志超时") from err
    except subprocess.CalledProcessError as err:
        # Do not echo adb stderr because some vendor logs include identifiers.
        raise StatusReadError(f"adb 读取失败（退出码 {err.returncode}）") from err
    return completed.stdout


def read_latest_adb_log(adb: str, serial: str | None) -> str:
    """Read the newest SDK log without starting or interacting with the app."""
    base = _adb_base(adb, serial)
    listing = _run_adb(
        base
        + [
            "shell",
            "ls",
            "-1t",
            f"{REMOTE_LOG_DIR}/",
        ]
    ).decode("utf-8", errors="replace")
    names = [name.strip() for name in listing.splitlines() if name.strip().endswith(".text")]
    if not names:
        raise StatusReadError("手机上没有找到 Control SDK 日志")
    newest = names[0]
    if "/" in newest or newest in {".", ".."}:
        raise StatusReadError("手机返回了异常的日志文件名")
    content = _run_adb(base + ["exec-out", "cat", f"{REMOTE_LOG_DIR}/{newest}"])
    return content.decode("utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读解析 ARCFOX 官方 Android App 的车辆状态缓存"
    )
    parser.add_argument(
        "--adb",
        default="adb",
        help="adb 可执行文件路径（默认：adb）",
    )
    parser.add_argument("--serial", help="多台设备时指定 adb serial")
    parser.add_argument(
        "--file",
        type=Path,
        help="解析本地日志文件，不访问手机（用于测试）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        text = (
            args.file.read_text(encoding="utf-8", errors="replace")
            if args.file
            else read_latest_adb_log(args.adb, args.serial)
        )
        output = normalize_status(parse_log(text))
    except (OSError, StatusReadError) as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
