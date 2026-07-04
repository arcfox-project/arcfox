"""Binary sensor platform for ARCFOX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ArcfoxEntity


@dataclass(frozen=True, kw_only=True)
class ArcfoxBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable = lambda vehicle: None


BINARY_SENSORS: tuple[ArcfoxBinarySensorDescription, ...] = (
    ArcfoxBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda vehicle: vehicle.is_charging,
    ),
    ArcfoxBinarySensorDescription(
        key="plugged_in",
        translation_key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda vehicle: vehicle.is_plugged_in,
    ),
    ArcfoxBinarySensorDescription(
        key="server_data_ready",
        translation_key="server_data_ready",
        entity_category=None,
        device_class=None,
        value_fn=lambda vehicle: (
            vehicle.raw.get("arcfox_connection_source") != "stub"
            and any(
                value is not None
                for value in (
                    vehicle.battery_pct,
                    vehicle.range_km,
                    vehicle.odometer_km,
                )
            )
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ArcfoxBinarySensor] = []
    for vehicle_id in coordinator.data:
        entities.extend(
            ArcfoxBinarySensor(coordinator, vehicle_id, description)
            for description in BINARY_SENSORS
        )
    async_add_entities(entities)


class ArcfoxBinarySensor(ArcfoxEntity, BinarySensorEntity):
    """ARCFOX binary sensor entity."""

    entity_description: ArcfoxBinarySensorDescription

    def __init__(self, coordinator, vehicle_id: str, description: ArcfoxBinarySensorDescription) -> None:
        super().__init__(coordinator, vehicle_id)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle_id}_{description.key}"

    @property
    def is_on(self):
        return self.entity_description.value_fn(self.vehicle)
