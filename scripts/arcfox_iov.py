#!/usr/bin/env python3
"""Standalone read-only ARCFOX IOv vehicle state query CLI.

Usage:
    ACCESS_TOKEN=... ARCFOX_VIN=... python3 scripts/arcfox_iov.py

Optional environment variables:
    ARCFOX_VIN     Vehicle VIN (required)
    ACCESS_TOKEN   App access token (required)
    ARCFOX_AID     Account aid (default: empty)
    ARCFOX_IMEI    15-char device IMEI (default: empty)
    ARCFOX_HOST    IOv gateway host (default: arcfoxapp-new-iov.bjev.com.cn)
    ARCFOX_PORT    IOv gateway port (default: 60115)

This tool is read-only: it only performs the online-status and full-state
queries.  It never sends control commands.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "arcfox"))

from iov import (  # noqa: E402
    ArcfoxIovClient,
    ArcfoxIovAuthError,
    ArcfoxIovError,
    DEFAULT_HOST,
    DEFAULT_PORT,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vin", default=os.environ.get("ARCFOX_VIN"))
    parser.add_argument("--aid", default=os.environ.get("ARCFOX_AID", ""))
    parser.add_argument("--imei", default=os.environ.get("ARCFOX_IMEI", ""))
    parser.add_argument("--host", default=os.environ.get("ARCFOX_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARCFOX_PORT", DEFAULT_PORT)))
    args = parser.parse_args()

    access_token = os.environ.get("ACCESS_TOKEN") or os.environ.get("ARCFOX_ACCESS_TOKEN")
    if not args.vin:
        print("error: VIN is required (--vin or ARCFOX_VIN)", file=sys.stderr)
        return 2
    if not access_token:
        print("error: ACCESS_TOKEN is required", file=sys.stderr)
        return 2

    client = ArcfoxIovClient(
        vin=args.vin,
        access_token=access_token,
        aid=args.aid,
        imei=args.imei,
        host=args.host,
        port=args.port,
    )
    try:
        client.connect()
        online = client.query_online()
        state = client.query_full_state()
    except ArcfoxIovAuthError as err:
        print(f"auth error: {err}", file=sys.stderr)
        return 3
    except ArcfoxIovError as err:
        print(f"query error: {err}", file=sys.stderr)
        return 4
    finally:
        client.close()

    state["online"] = online
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
