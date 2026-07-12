"""Data models for the ARCFOX integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


def _split_coordinates(value: Any) -> tuple[float | None, float | None]:
    """Parse ARCFOX coordinate strings like '116.431076;40.065837'."""
    if value in (None, ""):
        return None, None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(";")]
        if len(parts) == 2:
            longitude = _coerce_float(parts[0])
            latitude = _coerce_float(parts[1])
            return latitude, longitude
    return None, None


def _dig(payload: dict[str, Any] | None, *paths: tuple[str, ...] | str) -> Any:
    """Fetch a value from nested dictionaries using several candidate paths."""
    if not payload:
        return None

    for path in paths:
        keys = (path,) if isinstance(path, str) else path
        value: Any = payload
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if value is not None:
            return value
    return None


def _find_any(payload: Any, *keys: str) -> Any:
    """Recursively find the first non-empty value for any of the given keys."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for value in payload.values():
            found = _find_any(value, *keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_any(item, *keys)
            if found not in (None, ""):
                return found
    return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
        if match is None:
            return None
        value = match.group(0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
        if match is None:
            return None
        value = match.group(0)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "yes", "locked", "charging"}:
            return True
        if normalized in {"0", "false", "off", "no", "unlocked", "idle"}:
            return False
    return None


def _normalize_seat_mode(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"0", "off", "close", "closed", "disable", "disabled"}:
        return "off"
    if normalized in {"1", "heat", "heated", "heating", "warm"}:
        return "heat"
    if normalized in {"2", "wind", "vent", "ventilation", "venting", "cool"}:
        return "wind"
    return normalized


def _seat_option(mode: Any, level: Any) -> str | None:
    normalized_mode = _normalize_seat_mode(mode)
    normalized_level = _coerce_int(level)
    if normalized_mode is None:
        return None
    if normalized_mode == "off":
        return "off"
    if normalized_level is None or normalized_level <= 0:
        return None
    return f"{normalized_mode}_{normalized_level}"


def _seat_level_option(level: Any) -> str | None:
    normalized_level = _coerce_int(level)
    if normalized_level is None or normalized_level <= 0:
        return None
    return f"level_{max(1, min(3, normalized_level))}"


@dataclass(slots=True)
class ArcfoxVehicle:
    """Normalized vehicle state."""

    vehicle_id: str
    vin: str
    name: str
    model: str | None = None
    brand: str | None = "ARCFOX"
    battery_pct: float | None = None
    range_km: float | None = None
    odometer_km: float | None = None
    is_charging: bool | None = None
    is_plugged_in: bool | None = None
    is_locked: bool | None = None
    climate_on: bool | None = None
    climate_target_c: float | None = None
    steering_wheel_heat_on: bool | None = None
    front_defrost_on: bool | None = None
    rear_defrost_on: bool | None = None
    left_front_seat_mode: str | None = None
    left_front_seat_level: int | None = None
    left_front_seat_heat_level: int | None = None
    left_front_seat_wind_level: int | None = None
    right_front_seat_mode: str | None = None
    right_front_seat_level: int | None = None
    right_front_seat_heat_level: int | None = None
    right_front_seat_wind_level: int | None = None
    left_back_seat_mode: str | None = None
    left_back_seat_level: int | None = None
    left_back_seat_heat_level: int | None = None
    left_back_seat_wind_level: int | None = None
    right_back_seat_mode: str | None = None
    right_back_seat_level: int | None = None
    right_back_seat_heat_level: int | None = None
    right_back_seat_wind_level: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    inside_temp_c: float | None = None
    outside_temp_c: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        status_payload: dict[str, Any] | None = None,
    ) -> "ArcfoxVehicle":
        """Create a normalized vehicle object from raw API data."""
        combined = {**payload, **(status_payload or {})}
        position = _dig(combined, "position", "location", ("status", "position")) or {}

        vehicle_id = str(
            _dig(
                combined,
                "vehicleId",
                "vehicle_id",
                "id",
                ("vehicle", "id"),
            )
            or _dig(payload, "vin")
            or "unknown"
        )

        vin = str(
            _dig(
                combined,
                "vin",
                "VIN",
                ("vehicle", "vin"),
            )
            or vehicle_id
        )
        fallback_latitude, fallback_longitude = _split_coordinates(
            _find_any(combined, "carLocation")
            or _dig(
                combined,
                ("status", "carLocation"),
                ("vehicleState", "carLocation"),
                ("dataBean", "carLocation"),
            )
        )

        return cls(
            vehicle_id=vehicle_id,
            vin=vin,
            name=str(
                _dig(combined, "vehicleName", "name", ("vehicle", "name")) or vin
            ),
            model=_dig(combined, "model", "seriesName", ("vehicle", "model")),
            battery_pct=_coerce_float(
                _find_any(
                    combined,
                    "batteryPct",
                    "battery_pct",
                    "soc",
                    "SOC",
                    "chargeLeft",
                    "chargingleft",
                    "chargeLeftPercent",
                    "fuelSoc",
                    "vcuSoc",
                    "batteryCapacity",
                    "batteryStatus",
                    "currentBattery",
                    "battery",
                )
                or _dig(
                    combined,
                    ("status", "soc"),
                    ("status", "chargingleft"),
                    ("status", "fuelSoc"),
                    ("status", "batteryPct"),
                    ("status", "chargeLeft"),
                    ("status", "vcuSoc"),
                    ("status", "batteryCapacity"),
                    ("vehicleState", "soc"),
                    ("vehicleState", "chargingleft"),
                    ("vehicleState", "chargeLeft"),
                    ("vehicleState", "vcuSoc"),
                    ("vehicleState", "batteryCapacity"),
                    ("vehicleState", "currentBattery"),
                    ("status", "currentBattery"),
                    ("dataBean", "currentBattery"),
                    ("vehicleInfo", "soc"),
                    ("vehicleData", "soc"),
                    ("battery", "percent"),
                )
            ),
            range_km=_coerce_float(
                _find_any(
                    combined,
                    "rangeKm",
                    "range_km",
                    "enduranceMileage",
                    "sumRemainingMileage",
                    "cltcRemainingMileage",
                    "wltcRemainingMileage",
                    "nedcRemainingMileage",
                    "drvMileage",
                    "limitedDriving",
                    "mileage",
                    "current",
                    "vehicleRange",
                    "vcuSumRemainingMileage",
                    "vcuWltcRemainingMileage",
                    "vcuNedcRemainingMileage",
                    "vcuCltcRemainingMileage",
                )
                or _dig(
                    combined,
                    ("status", "rangeKm"),
                    ("status", "sumRemainingMileage"),
                    ("status", "cltcRemainingMileage"),
                    ("status", "wltcRemainingMileage"),
                    ("status", "nedcRemainingMileage"),
                    ("status", "drvMileage"),
                    ("status", "limitedDriving"),
                    ("status", "mileage"),
                    ("status", "current"),
                    ("status", "enduranceMileage"),
                    ("status", "vcuSumRemainingMileage"),
                    ("status", "vcuWltcRemainingMileage"),
                    ("status", "vcuNedcRemainingMileage"),
                    ("status", "vcuCltcRemainingMileage"),
                    ("status", "vehicleRange"),
                    ("vehicleState", "rangeKm"),
                    ("vehicleState", "sumRemainingMileage"),
                    ("vehicleState", "cltcRemainingMileage"),
                    ("vehicleState", "wltcRemainingMileage"),
                    ("vehicleState", "nedcRemainingMileage"),
                    ("vehicleState", "drvMileage"),
                    ("vehicleState", "limitedDriving"),
                    ("vehicleState", "mileage"),
                    ("vehicleState", "current"),
                    ("vehicleState", "enduranceMileage"),
                    ("vehicleState", "vcuSumRemainingMileage"),
                    ("vehicleState", "vcuWltcRemainingMileage"),
                    ("vehicleState", "vcuNedcRemainingMileage"),
                    ("vehicleState", "vcuCltcRemainingMileage"),
                    ("vehicleState", "vehicleRange"),
                    ("vehicleInfo", "rangeKm"),
                    ("vehicleInfo", "sumRemainingMileage"),
                    ("vehicleInfo", "cltcRemainingMileage"),
                    ("vehicleInfo", "wltcRemainingMileage"),
                    ("vehicleInfo", "nedcRemainingMileage"),
                    ("vehicleInfo", "drvMileage"),
                    ("battery", "range"),
                )
            ),
            odometer_km=_coerce_float(
                _find_any(
                    combined,
                    "odometerKm",
                    "odometer_km",
                    "totalMileage",
                    "totalMileageValue",
                    "kmTotal",
                    "totalMileageKm",
                    "vehicleMileage",
                    "mileage",
                )
                or _dig(
                    combined,
                    ("status", "odometerKm"),
                    ("status", "totalMileage"),
                    ("status", "totalMileageValue"),
                    ("status", "kmTotal"),
                    ("status", "mileage"),
                    ("vehicleState", "odometerKm"),
                    ("vehicleState", "totalMileage"),
                    ("vehicleState", "totalMileageValue"),
                    ("vehicleState", "kmTotal"),
                    ("vehicleState", "mileage"),
                    ("dataBean", "totalMileage"),
                    ("dataBean", "totalMileageValue"),
                    ("dataBean", "kmTotal"),
                    ("dataBean", "mileage"),
                    ("vehicle", "mileage"),
                )
            ),
            is_charging=_coerce_bool(
                _dig(
                    combined,
                    "charging",
                    "isCharging",
                    ("status", "charging"),
                    ("charge", "active"),
                )
            ),
            is_plugged_in=_coerce_bool(
                _dig(
                    combined,
                    "pluggedIn",
                    "isPluggedIn",
                    ("status", "pluggedIn"),
                    ("charge", "plugged"),
                )
            ),
            is_locked=_coerce_bool(
                _dig(
                    combined,
                    "locked",
                    "doorLock",
                    ("status", "locked"),
                    ("doors", "locked"),
                )
            ),
            climate_on=_coerce_bool(
                _dig(
                    combined,
                    "climateOn",
                    "airConditionOn",
                    "airState",
                    ("status", "climateOn"),
                    ("status", "airState"),
                    ("hvac", "running"),
                )
            ),
            climate_target_c=_coerce_float(
                _dig(
                    combined,
                    "targetTemp",
                    "setTemp",
                    "acSetTemp",
                    ("status", "targetTemp"),
                    ("hvac", "setTemp"),
                )
            ),
            steering_wheel_heat_on=_coerce_bool(
                _dig(
                    combined,
                    "steeringWheelHeat",
                    "steeringWheelHeatOn",
                    ("status", "steeringWheelHeat"),
                    ("hvac", "steeringWheelHeat"),
                )
            ),
            front_defrost_on=_coerce_bool(
                _dig(
                    combined,
                    "frontDefrost",
                    "defrost",
                    ("status", "frontDefrost"),
                    ("hvac", "frontDefrost"),
                )
            ),
            rear_defrost_on=_coerce_bool(
                _dig(
                    combined,
                    "rearDefrost",
                    "backDefrost",
                    ("status", "rearDefrost"),
                    ("hvac", "rearDefrost"),
                )
            ),
            left_front_seat_mode=_normalize_seat_mode(
                _dig(
                    combined,
                    "leftFrontMode",
                    ("status", "leftFrontMode"),
                    ("seat", "leftFrontMode"),
                )
            ),
            left_front_seat_level=_coerce_int(
                _dig(
                    combined,
                    "leftFrontLevel",
                    ("status", "leftFrontLevel"),
                    ("seat", "leftFrontLevel"),
                )
            ),
            left_front_seat_heat_level=_coerce_int(
                _dig(
                    combined,
                    "leftFrontHeatLevel",
                    ("status", "leftFrontHeatLevel"),
                    ("seat", "leftFrontHeatLevel"),
                )
            ),
            left_front_seat_wind_level=_coerce_int(
                _dig(
                    combined,
                    "leftFrontWindLevel",
                    ("status", "leftFrontWindLevel"),
                    ("seat", "leftFrontWindLevel"),
                )
            ),
            right_front_seat_mode=_normalize_seat_mode(
                _dig(
                    combined,
                    "rightFrontMode",
                    ("status", "rightFrontMode"),
                    ("seat", "rightFrontMode"),
                )
            ),
            right_front_seat_level=_coerce_int(
                _dig(
                    combined,
                    "rightFrontLevel",
                    ("status", "rightFrontLevel"),
                    ("seat", "rightFrontLevel"),
                )
            ),
            right_front_seat_heat_level=_coerce_int(
                _dig(
                    combined,
                    "rightFrontHeatLevel",
                    ("status", "rightFrontHeatLevel"),
                    ("seat", "rightFrontHeatLevel"),
                )
            ),
            right_front_seat_wind_level=_coerce_int(
                _dig(
                    combined,
                    "rightFrontWindLevel",
                    ("status", "rightFrontWindLevel"),
                    ("seat", "rightFrontWindLevel"),
                )
            ),
            left_back_seat_mode=_normalize_seat_mode(
                _dig(
                    combined,
                    "leftBackMode",
                    ("status", "leftBackMode"),
                    ("seat", "leftBackMode"),
                )
            ),
            left_back_seat_level=_coerce_int(
                _dig(
                    combined,
                    "leftBackLevel",
                    ("status", "leftBackLevel"),
                    ("seat", "leftBackLevel"),
                )
            ),
            left_back_seat_heat_level=_coerce_int(
                _dig(
                    combined,
                    "leftBackHeatLevel",
                    ("status", "leftBackHeatLevel"),
                    ("seat", "leftBackHeatLevel"),
                )
            ),
            left_back_seat_wind_level=_coerce_int(
                _dig(
                    combined,
                    "leftBackWindLevel",
                    ("status", "leftBackWindLevel"),
                    ("seat", "leftBackWindLevel"),
                )
            ),
            right_back_seat_mode=_normalize_seat_mode(
                _dig(
                    combined,
                    "rightBackMode",
                    ("status", "rightBackMode"),
                    ("seat", "rightBackMode"),
                )
            ),
            right_back_seat_level=_coerce_int(
                _dig(
                    combined,
                    "rightBackLevel",
                    ("status", "rightBackLevel"),
                    ("seat", "rightBackLevel"),
                )
            ),
            right_back_seat_heat_level=_coerce_int(
                _dig(
                    combined,
                    "rightBackHeatLevel",
                    ("status", "rightBackHeatLevel"),
                    ("seat", "rightBackHeatLevel"),
                )
            ),
            right_back_seat_wind_level=_coerce_int(
                _dig(
                    combined,
                    "rightBackWindLevel",
                    ("status", "rightBackWindLevel"),
                    ("seat", "rightBackWindLevel"),
                )
            ),
            inside_temp_c=_coerce_float(
                _find_any(
                    combined,
                    "insideTemp",
                    "insideTemperature",
                    "inTemp",
                    "cabinTemp",
                    "airTemperature",
                )
                or _dig(
                    combined,
                    "insideTemp",
                    ("status", "insideTemp"),
                    ("status", "insideTemperature"),
                    ("status", "airTemperature"),
                    ("dataBean", "airTemperature"),
                    ("hvac", "insideTemp"),
                )
            ),
            outside_temp_c=_coerce_float(
                _find_any(
                    combined,
                    "outsideTemp",
                    "outsideTemperature",
                    "outTemp",
                    "ambientTemp",
                    "batteryTemperature",
                    "driveTemperature",
                )
                or _dig(
                    combined,
                    "outsideTemp",
                    ("status", "outsideTemp"),
                    ("status", "outsideTemperature"),
                    ("status", "driveTemperature"),
                    ("dataBean", "driveTemperature"),
                    ("hvac", "outsideTemp"),
                )
            ),
            latitude=_coerce_float(
                _dig(position, "latitude", "lat")
                or _dig(combined, "latitude", "lat")
                or fallback_latitude
            ),
            longitude=_coerce_float(
                _dig(position, "longitude", "lng", "lon")
                or _dig(combined, "longitude", "lng", "lon")
                or fallback_longitude
            ),
            raw=combined,
        )

    def seat_option(self, seat: str, mode: str | None = None) -> str | None:
        """Return the current select option for a seat controller."""
        if mode == "heat":
            if seat == "left_front":
                return _seat_level_option(self.left_front_seat_heat_level)
            if seat == "right_front":
                return _seat_level_option(self.right_front_seat_heat_level)
            if seat == "left_back":
                return _seat_level_option(self.left_back_seat_heat_level)
            if seat == "right_back":
                return _seat_level_option(self.right_back_seat_heat_level)
        if mode == "wind":
            if seat == "left_front":
                return _seat_level_option(self.left_front_seat_wind_level)
            if seat == "right_front":
                return _seat_level_option(self.right_front_seat_wind_level)
            if seat == "left_back":
                return _seat_level_option(self.left_back_seat_wind_level)
            if seat == "right_back":
                return _seat_level_option(self.right_back_seat_wind_level)
        if seat == "left_front":
            return _seat_option(self.left_front_seat_mode, self.left_front_seat_level)
        if seat == "right_front":
            return _seat_option(self.right_front_seat_mode, self.right_front_seat_level)
        if seat == "left_back":
            return _seat_option(self.left_back_seat_mode, self.left_back_seat_level)
        if seat == "right_back":
            return _seat_option(self.right_back_seat_mode, self.right_back_seat_level)
        return None

    @property
    def seat_comfort_master_on(self) -> bool | None:
        """Return whether any seat heat or wind control is active."""
        values = (
            self.left_front_seat_heat_level,
            self.right_front_seat_heat_level,
            self.left_back_seat_heat_level,
            self.right_back_seat_heat_level,
            self.left_front_seat_wind_level,
            self.right_front_seat_wind_level,
            self.left_back_seat_wind_level,
            self.right_back_seat_wind_level,
        )
        if all(value is None for value in values):
            return None
        return any(value not in (None, 0) for value in values)
