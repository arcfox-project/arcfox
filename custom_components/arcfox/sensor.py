"""Sensor platform for ARCFOX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfLength, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ArcfoxEntity


def _charge_state_label(vehicle) -> str | None:
    """Return a readable charge-state label derived from live signals."""
    if vehicle.is_charging is True:
        return "充电中"
    if vehicle.is_plugged_in is True:
        return "已插枪未充电"
    if vehicle.is_plugged_in is False:
        return "未插枪"
    return None


@dataclass(frozen=True, kw_only=True)
class ArcfoxSensorDescription(SensorEntityDescription):
    value_fn: Callable = lambda vehicle: None


SENSORS: tuple[ArcfoxSensorDescription, ...] = (
    ArcfoxSensorDescription(
        key="battery_pct",
        translation_key="battery_pct",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda vehicle: vehicle.battery_pct,
    ),
    ArcfoxSensorDescription(
        key="range_km",
        translation_key="range_km",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda vehicle: vehicle.range_km,
    ),
    ArcfoxSensorDescription(
        key="odometer_km",
        translation_key="odometer_km",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda vehicle: vehicle.odometer_km,
    ),
    ArcfoxSensorDescription(
        key="inside_temp_c",
        translation_key="inside_temp_c",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.inside_temp_c,
    ),
    ArcfoxSensorDescription(
        key="outside_temp_c",
        translation_key="outside_temp_c",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.outside_temp_c,
    ),
    ArcfoxSensorDescription(
        key="battery_temp_c",
        translation_key="battery_temp_c",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.battery_temp_c,
    ),
    ArcfoxSensorDescription(
        key="tire_pressure_fl_kpa",
        translation_key="tire_pressure_fl_kpa",
        native_unit_of_measurement="kPa",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.tire_pressure_fl_kpa,
    ),
    ArcfoxSensorDescription(
        key="tire_pressure_fr_kpa",
        translation_key="tire_pressure_fr_kpa",
        native_unit_of_measurement="kPa",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.tire_pressure_fr_kpa,
    ),
    ArcfoxSensorDescription(
        key="tire_pressure_rl_kpa",
        translation_key="tire_pressure_rl_kpa",
        native_unit_of_measurement="kPa",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.tire_pressure_rl_kpa,
    ),
    ArcfoxSensorDescription(
        key="tire_pressure_rr_kpa",
        translation_key="tire_pressure_rr_kpa",
        native_unit_of_measurement="kPa",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.tire_pressure_rr_kpa,
    ),
    ArcfoxSensorDescription(
        key="charge_state",
        translation_key="charge_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_charge_state_label,
    ),
    ArcfoxSensorDescription(
        key="charge_power_kw",
        translation_key="charge_power_kw",
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.charge_power_kw,
    ),
    ArcfoxSensorDescription(
        key="charge_voltage_v",
        translation_key="charge_voltage_v",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.charge_voltage_v,
    ),
    ArcfoxSensorDescription(
        key="charge_energy_kwh",
        translation_key="charge_energy_kwh",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.charge_energy_kwh,
    ),
    ArcfoxSensorDescription(
        key="target_soc",
        translation_key="target_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda vehicle: vehicle.target_soc,
    ),
    ArcfoxSensorDescription(
        key="connection_source",
        translation_key="connection_source",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:link-variant",
        value_fn=lambda vehicle: vehicle.raw.get("arcfox_connection_source"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ArcfoxSensor] = []
    for vehicle_id in coordinator.data:
        entities.extend(ArcfoxSensor(coordinator, vehicle_id, description) for description in SENSORS)
    async_add_entities(entities)


class ArcfoxSensor(ArcfoxEntity, SensorEntity):
    """ARCFOX sensor entity."""

    entity_description: ArcfoxSensorDescription

    def __init__(self, coordinator, vehicle_id: str, description: ArcfoxSensorDescription) -> None:
        super().__init__(coordinator, vehicle_id)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle_id}_{description.key}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.vehicle)
