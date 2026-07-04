"""Lock platform for ARCFOX."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
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
    async_add_entities(ArcfoxDoorLock(coordinator, vehicle_id) for vehicle_id in coordinator.data)


class ArcfoxDoorLock(ArcfoxEntity, LockEntity):
    """Vehicle lock entity."""

    _attr_translation_key = "door_lock"

    def __init__(self, coordinator, vehicle_id: str) -> None:
        super().__init__(coordinator, vehicle_id)
        self._attr_unique_id = f"{vehicle_id}_door_lock"

    @property
    def is_locked(self) -> bool | None:
        return self.vehicle.is_locked

    async def async_lock(self, **kwargs) -> None:
        await self.coordinator.client.async_set_lock(self.vehicle, True)
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs) -> None:
        await self.coordinator.client.async_set_lock(self.vehicle, False)
        await self.coordinator.async_request_refresh()
