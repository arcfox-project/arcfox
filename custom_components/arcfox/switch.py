"""Switch platform for ARCFOX."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .entity import ArcfoxEntity

_REFRESH_DELAY_SECONDS = 15


@dataclass(frozen=True, kw_only=True)
class ArcfoxSwitchDescription(SwitchEntityDescription):
    action: str
    value_fn: Callable = lambda vehicle: None


SWITCHES: tuple[ArcfoxSwitchDescription, ...] = (
    ArcfoxSwitchDescription(
        key="climate",
        translation_key="climate",
        icon="mdi:fan",
        action="climate",
        value_fn=lambda vehicle: vehicle.climate_on,
    ),
    ArcfoxSwitchDescription(
        key="steering_wheel_heat",
        translation_key="steering_wheel_heat",
        icon="mdi:steering",
        action="steering_wheel_heat",
        value_fn=lambda vehicle: vehicle.steering_wheel_heat_on,
    ),
    ArcfoxSwitchDescription(
        key="front_defrost",
        translation_key="front_defrost",
        icon="mdi:car-defrost-front",
        action="front_defrost",
        value_fn=lambda vehicle: vehicle.front_defrost_on,
    ),
    ArcfoxSwitchDescription(
        key="rear_defrost",
        translation_key="rear_defrost",
        icon="mdi:car-defrost-rear",
        action="rear_defrost",
        value_fn=lambda vehicle: vehicle.rear_defrost_on,
    ),
    ArcfoxSwitchDescription(
        key="seat_comfort_master",
        translation_key="seat_comfort_master",
        icon="mdi:car-seat",
        action="seat_comfort_master",
        value_fn=lambda vehicle: vehicle.seat_comfort_master_on,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ArcfoxCommandSwitch] = []
    for vehicle_id in coordinator.data:
        entities.extend(
            ArcfoxCommandSwitch(coordinator, vehicle_id, description)
            for description in SWITCHES
        )
    async_add_entities(entities)


class ArcfoxCommandSwitch(ArcfoxEntity, SwitchEntity):
    """ARCFOX switch entity."""

    entity_description: ArcfoxSwitchDescription

    def __init__(self, coordinator, vehicle_id: str, description: ArcfoxSwitchDescription) -> None:
        super().__init__(coordinator, vehicle_id)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle_id}_{description.key}"
        self._optimistic_on: bool | None = None
        self._optimistic_since = 0.0
        self._command_in_flight = False
        self._refresh_cancel: Any = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_on is not None:
            return self._optimistic_on
        return self.entity_description.value_fn(self.vehicle)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Keep the optimistic value until the vehicle has had time to react."""
        if (
            self._optimistic_on is not None
            and time.monotonic() - self._optimistic_since < _REFRESH_DELAY_SECONDS
        ):
            super()._handle_coordinator_update()
            return
        self._optimistic_on = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_on(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_on(False)

    async def _set_on(self, enabled: bool) -> None:
        if self._command_in_flight:
            return
        self._command_in_flight = True
        self._optimistic_on = enabled
        self._optimistic_since = time.monotonic()
        self.async_write_ha_state()
        try:
            await self._send_switch_command(enabled)
        except Exception:
            self._optimistic_on = None
            self.async_write_ha_state()
            raise
        finally:
            self._command_in_flight = False
        self._schedule_refresh()

    async def _send_switch_command(self, enabled: bool) -> None:
        client = self.coordinator.client
        vehicle = self.vehicle
        action = self.entity_description.action
        if action == "climate":
            await client.async_set_climate(vehicle, enabled)
        elif action == "steering_wheel_heat":
            await client.async_set_steering_wheel_heat(vehicle, enabled)
        elif action == "front_defrost":
            await client.async_set_front_defrost(vehicle, enabled)
        elif action == "rear_defrost":
            await client.async_set_rear_defrost(vehicle, enabled)
        elif action == "seat_comfort_master":
            await client.async_set_seat_comfort_master(vehicle, enabled)

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
