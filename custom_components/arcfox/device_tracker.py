"""Device tracker platform for ARCFOX."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ArcfoxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(ArcfoxDeviceTracker(coordinator, vehicle_id) for vehicle_id in coordinator.data)


class ArcfoxDeviceTracker(ArcfoxEntity, TrackerEntity):
    """ARCFOX location entity."""

    _attr_translation_key = "location"

    def __init__(self, coordinator, vehicle_id: str) -> None:
        super().__init__(coordinator, vehicle_id)
        self._attr_unique_id = f"{vehicle_id}_location"

    @property
    def latitude(self) -> float | None:
        return self.vehicle.latitude

    @property
    def longitude(self) -> float | None:
        return self.vehicle.longitude

    @property
    def location_accuracy(self) -> int:
        return 100

    @property
    def source_type(self):
        return SourceType.GPS
