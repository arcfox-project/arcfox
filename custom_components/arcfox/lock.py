"""Lock platform for ARCFOX."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .entity import ArcfoxEntity

_REFRESH_DELAY_SECONDS = 15


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
        self._optimistic_locked: bool | None = None
        self._optimistic_since = 0.0
        self._command_in_flight = False
        self._refresh_cancel: Any = None

    @property
    def is_locked(self) -> bool | None:
        if self._optimistic_locked is not None:
            return self._optimistic_locked
        return self.vehicle.is_locked

    @callback
    def _handle_coordinator_update(self) -> None:
        """Keep the optimistic value until the vehicle has had time to react."""
        if (
            self._optimistic_locked is not None
            and time.monotonic() - self._optimistic_since < _REFRESH_DELAY_SECONDS
        ):
            super()._handle_coordinator_update()
            return
        self._optimistic_locked = None
        super()._handle_coordinator_update()

    async def async_lock(self, **kwargs) -> None:
        await self._set_locked(True)

    async def async_unlock(self, **kwargs) -> None:
        await self._set_locked(False)

    async def _set_locked(self, locked: bool) -> None:
        if self._command_in_flight:
            return
        self._command_in_flight = True
        self._optimistic_locked = locked
        self._optimistic_since = time.monotonic()
        self.async_write_ha_state()
        try:
            await self.coordinator.client.async_set_lock(self.vehicle, locked)
        except Exception:
            self._optimistic_locked = None
            self.async_write_ha_state()
            raise
        finally:
            self._command_in_flight = False
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._refresh_cancel is not None:
            self._refresh_cancel()
        self._refresh_cancel = async_call_later(
            self.hass, _REFRESH_DELAY_SECONDS, self._refresh_after_command
        )

    @callback
    def _refresh_after_command(self, _now: Any = None) -> None:
        self._refresh_cancel = None
        self.coordinator.async_request_refresh()

    async def async_will_remove_from_hass(self) -> None:
        if self._refresh_cancel is not None:
            self._refresh_cancel()
            self._refresh_cancel = None
        await super().async_will_remove_from_hass()
