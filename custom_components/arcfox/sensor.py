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
