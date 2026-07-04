"""ARCFOX command payload helpers."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable


_CMD7_SLOTS: dict[str, tuple[str, int]] = {
    "window": ("p3", 1),
    "defrost": ("p8", 2),
    "door": ("p9", 4),
    "trunk": ("p10", 8),
    "flash_honk": ("p11", 16),
    "sunroof": ("p12", 32),
}

_CMD8_SEAT_SLOTS: dict[str, tuple[str, int]] = {
    "left_front": ("p3", 1),
    "right_front": ("p8", 2),
    "left_back": ("p9", 4),
    "right_back": ("p10", 8),
}


@dataclass(slots=True)
class ArcfoxCommandPayload:
    """Protocol payload for a remote control command."""

    group: int
    cmd: int
    c: int
    p2: int | None = None
    p3: int | None = None
    p8: int | None = None
    p9: int | None = None
    p10: int | None = None
    p11: int | None = None
    p12: int | None = None
    p1: int | None = None

    def to_dict(self) -> dict[str, int]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True, slots=True)
class ArcfoxCommandSpec:
    """High-level command specification for a vehicle action."""

    action: str
    command: str
    group: int | None = None
    cmd: int | None = None
    builder: Callable[..., ArcfoxCommandPayload] | None = None
    notes: str | None = None

    def build_payload(self, *args, **kwargs) -> ArcfoxCommandPayload | None:
        if self.builder is None:
            return None
        return self.builder(*args, **kwargs)


def build_cmd7_payload(control: str, enabled: bool) -> ArcfoxCommandPayload:
    """Build the body-control payload for `cmd=7`."""
    slot_name, _ = _CMD7_SLOTS[control]
    return ArcfoxCommandPayload(
        group=7,
        cmd=1,
        c=1 if enabled else 2,
        **{slot_name: 1 if enabled else 4},
    )


def build_cmd2_temperature_payload(temperature_c: float) -> ArcfoxCommandPayload:
    """Build the HVAC temperature payload for `cmd=2`."""
    temp = int(round(temperature_c))
    temp = max(16, min(33, temp))
    return ArcfoxCommandPayload(group=10, cmd=2, c=1, p1=temp)


def build_cmd33_power_payload(enabled: bool) -> ArcfoxCommandPayload:
    """Build the main HVAC power payload for `cmd=33`."""
    return ArcfoxCommandPayload(group=10, cmd=33, c=1 if enabled else 2)


def build_cmd38_defrost_payload(front: bool, enabled: bool) -> ArcfoxCommandPayload:
    """Build the defrost payload for `cmd=38`."""
    return ArcfoxCommandPayload(
        group=10,
        cmd=38,
        c=1 if enabled else 2,
        p1=1 if front else 2,
    )


def build_cmd16_steering_wheel_heat_payload(enabled: bool) -> ArcfoxCommandPayload:
    """Build the steering wheel heat payload for `cmd=16`."""
    return ArcfoxCommandPayload(group=10, cmd=16, c=1 if enabled else 2, p1=1)


def build_cmd6_seat_comfort_master_payload(enabled: bool) -> ArcfoxCommandPayload:
    """Build the master payload for seat heat / wind control.

    This is the most plausible current mapping for `cmd=6`.
    """
    return ArcfoxCommandPayload(group=10, cmd=6, c=1 if enabled else 2, p2=1)


def build_cmd8_seat_payload(
    seat: str,
    level: int,
    *,
    enabled: bool = True,
) -> ArcfoxCommandPayload:
    """Build the seat heat/vent payload for `cmd=8`.

    The payload structure matches the decompiled slot layout. The actual heat vs
    wind mode is carried separately by the caller because the exact bit that
    distinguishes the two modes is still not fully verified.
    """
    slot_name, bit_value = _CMD8_SEAT_SLOTS[seat]
    payload = ArcfoxCommandPayload(
        group=10,
        cmd=8,
        c=1 if enabled else 2,
        p2=bit_value,
        **{slot_name: 4 if not enabled else max(1, min(3, int(level)))},
    )
    return payload


COMMAND_SPECS: dict[str, ArcfoxCommandSpec] = {
    "lock": ArcfoxCommandSpec(action="lock", command="lock"),
    "unlock": ArcfoxCommandSpec(action="unlock", command="unlock"),
    "climate_on": ArcfoxCommandSpec(
        action="climate_on",
        command="climate_on",
        group=10,
        cmd=33,
        builder=lambda enabled: build_cmd33_power_payload(enabled),
        notes="cmd=33 main HVAC power",
    ),
    "climate_off": ArcfoxCommandSpec(
        action="climate_off",
        command="climate_off",
        group=10,
        cmd=33,
        builder=lambda enabled: build_cmd33_power_payload(enabled),
        notes="cmd=33 main HVAC power",
    ),
    "set_climate_temperature": ArcfoxCommandSpec(
        action="set_climate_temperature",
        command="set_climate_temperature",
        group=10,
        cmd=2,
        builder=lambda temperature: build_cmd2_temperature_payload(temperature),
        notes="cmd=2 HVAC temperature",
    ),
    "steering_wheel_heat_on": ArcfoxCommandSpec(
        action="steering_wheel_heat_on",
        command="steering_wheel_heat_on",
        group=10,
        cmd=16,
        builder=lambda enabled: build_cmd16_steering_wheel_heat_payload(enabled),
        notes="cmd=16 steering wheel heat",
    ),
    "steering_wheel_heat_off": ArcfoxCommandSpec(
        action="steering_wheel_heat_off",
        command="steering_wheel_heat_off",
        group=10,
        cmd=16,
        builder=lambda enabled: build_cmd16_steering_wheel_heat_payload(enabled),
        notes="cmd=16 steering wheel heat",
    ),
    "front_defrost_on": ArcfoxCommandSpec(
        action="front_defrost_on",
        command="front_defrost_on",
        group=10,
        cmd=38,
        builder=lambda enabled: build_cmd38_defrost_payload(True, enabled),
        notes="cmd=38 front defrost",
    ),
    "front_defrost_off": ArcfoxCommandSpec(
        action="front_defrost_off",
        command="front_defrost_off",
        group=10,
        cmd=38,
        builder=lambda enabled: build_cmd38_defrost_payload(True, enabled),
        notes="cmd=38 front defrost",
    ),
    "rear_defrost_on": ArcfoxCommandSpec(
        action="rear_defrost_on",
        command="rear_defrost_on",
        group=10,
        cmd=38,
        builder=lambda enabled: build_cmd38_defrost_payload(False, enabled),
        notes="cmd=38 rear defrost",
    ),
    "rear_defrost_off": ArcfoxCommandSpec(
        action="rear_defrost_off",
        command="rear_defrost_off",
        group=10,
        cmd=38,
        builder=lambda enabled: build_cmd38_defrost_payload(False, enabled),
        notes="cmd=38 rear defrost",
    ),
    "seat_comfort_master_on": ArcfoxCommandSpec(
        action="seat_comfort_master_on",
        command="seat_comfort_master_on",
        group=10,
        cmd=6,
        builder=lambda enabled: build_cmd6_seat_comfort_master_payload(enabled),
        notes="cmd=6 seat comfort master",
    ),
    "seat_comfort_master_off": ArcfoxCommandSpec(
        action="seat_comfort_master_off",
        command="seat_comfort_master_off",
        group=10,
        cmd=6,
        builder=lambda enabled: build_cmd6_seat_comfort_master_payload(enabled),
        notes="cmd=6 seat comfort master",
    ),
    "seat_heat": ArcfoxCommandSpec(
        action="seat_heat",
        command="seat_heat",
        group=10,
        cmd=8,
        builder=lambda seat, level, enabled=True: build_cmd8_seat_payload(
            seat, level, enabled=enabled
        ),
        notes="cmd=8 seat heat",
    ),
    "seat_wind": ArcfoxCommandSpec(
        action="seat_wind",
        command="seat_wind",
        group=10,
        cmd=8,
        builder=lambda seat, level, enabled=True: build_cmd8_seat_payload(
            seat, level, enabled=enabled
        ),
        notes="cmd=8 seat wind",
    ),
    "wake_up": ArcfoxCommandSpec(action="wake_up", command="wake_up"),
    "window_open": ArcfoxCommandSpec(
        action="window_open",
        command="window_open",
        group=7,
        cmd=1,
        builder=lambda enabled: build_cmd7_payload("window", enabled),
        notes="cmd=7 window",
    ),
    "window_close": ArcfoxCommandSpec(
        action="window_close",
        command="window_close",
        group=7,
        cmd=1,
        builder=lambda enabled: build_cmd7_payload("window", enabled),
        notes="cmd=7 window",
    ),
    "sunroof_open": ArcfoxCommandSpec(
        action="sunroof_open",
        command="sunroof_open",
        group=7,
        cmd=1,
        builder=lambda enabled: build_cmd7_payload("sunroof", enabled),
        notes="cmd=7 sunroof",
    ),
    "sunroof_close": ArcfoxCommandSpec(
        action="sunroof_close",
        command="sunroof_close",
        group=7,
        cmd=1,
        builder=lambda enabled: build_cmd7_payload("sunroof", enabled),
        notes="cmd=7 sunroof",
    ),
    "trunk_open": ArcfoxCommandSpec(
        action="trunk_open",
        command="trunk_open",
        group=7,
        cmd=1,
        builder=lambda enabled: build_cmd7_payload("trunk", enabled),
        notes="cmd=7 trunk",
    ),
    "flash_honk": ArcfoxCommandSpec(
        action="flash_honk",
        command="flash_honk",
        group=7,
        cmd=1,
        builder=lambda enabled: build_cmd7_payload("flash_honk", enabled),
        notes="cmd=7 flash_honk",
    ),
}
