#!/usr/bin/env python3
"""Tests for the read-only ARCFOX ADB log parser."""

from __future__ import annotations

from datetime import datetime
import unittest

from arcfox_adb_status import normalize_status, parse_log


class ParseLogTest(unittest.TestCase):
    def test_merges_full_state_and_newer_door_update(self) -> None:
        log = "\n".join(
            (
                '2026-07-16 09:00:00.100,VIN:SECRET,向APP反馈数据库车辆状态:'
                '{"carControlStateBean":{"currentBattery":"55.5","mileage":"321.0",'
                '"airState":"0","chargeState":"1","leftFrontDoor":"0",'
                '"rightFrontDoor":"0","leftBackDoor":"0","rightBackDoor":"0",'
                '"trunkState":"0","windowState":"0","skylightState":"0",'
                '"lockState":"0"},"isSuccess":true,"token":"SECRET"}',
                '2026-07-16 09:05:00.200,VIN:SECRET,向APP反馈主动上报停车时门窗状态上报:'
                '{"carControlStateBean":{"leftFrontDoor":"1","windowState":"1"},'
                '"isSuccess":true,"token":"SECRET"}',
                # Duplicated diagnostic wrapper must never be parsed.
                '2026-07-16 09:06:00.000,VIN:SECRET,向APP返回SDK日志:'
                '{"msg":"token and location","isSuccess":true}',
            )
        )

        parsed = parse_log(log)
        output = normalize_status(parsed)

        self.assertEqual(parsed.observed_at, datetime(2026, 7, 16, 9, 5, 0, 200000))
        self.assertEqual(output["battery_pct"], 55.5)
        self.assertEqual(output["range_km"], 321.0)
        self.assertFalse(output["doors"]["front_left_closed"])
        self.assertFalse(output["all_doors_closed"])
        self.assertFalse(output["all_windows_closed"])
        self.assertNotIn("vin", output)
        self.assertNotIn("token", output)


if __name__ == "__main__":
    unittest.main()
