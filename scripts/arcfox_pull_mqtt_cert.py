#!/usr/bin/env python3
"""Pull the ARCFOX app's dynamic MQTT client certificate from a device.

The broker requires mutual TLS.  After a successful login the app stores the
client identity as ``files/<userId>.crt`` and ``files/<userId>.key`` (PKCS8
PEM).  This script locates and downloads those files so they can be referenced
by the Home Assistant integration's ``mqtt_certfile`` / ``mqtt_keyfile``.

Read-only: it only lists and pulls files; it never writes to the device.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_PACKAGE = "com.bjev.arcfox"


def _adb(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["adb", *args], capture_output=True, text=True)


def _ls_files(package: str) -> list[str]:
    app_files = f"/data/data/{package}/files"
    for cmd in (
        [f"run-as {package} ls {app_files}"],
        [f"shell su 0 ls {app_files}"],
        [f"shell ls {app_files}"],
    ):
        proc = _adb(cmd)
        if proc.returncode == 0:
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--out", default=".", help="Local directory for pulled files")
    parser.add_argument("--user-id", default=None, help="App account userId (filename prefix)")
    args = parser.parse_args()

    proc = _adb(["devices"])
    attached = [l for l in proc.stdout.splitlines() if l.strip() and "\t" in l]
    if not attached:
        print("No adb device attached. Start the emulator and log in to the app first.", file=sys.stderr)
        return 2

    _adb(["root"])

    names = _ls_files(args.package)
    if not names:
        print(f"Could not list app files for {args.package}. The app may not be debuggable/rooted here.", file=sys.stderr)
        return 3

    candidates = [n for n in names if n.endswith((".crt", ".key", ".pem"))]
    if args.user_id:
        filtered = [n for n in candidates if n.startswith(args.user_id)]
        if filtered:
            candidates = filtered
    if not candidates:
        print("No certificate files found. Files present:", names)
        return 4

    app_files = f"/data/data/{args.package}/files"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pulled = []
    for name in candidates:
        proc = _adb(["pull", f"{app_files}/{name}", str(out / name)])
        if proc.returncode == 0:
            pulled.append(name)

    if not pulled:
        print("Nothing pulled.", file=sys.stderr)
        return 5

    print("Pulled:", ", ".join(pulled))
    print("Set mqtt_certfile=<userId>.crt and mqtt_keyfile=<userId>.key in the ARCFOX integration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
