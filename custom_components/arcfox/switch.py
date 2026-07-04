"""Switch platform for ARCFOX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ArcfoxEntity


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

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.vehicle)

    async def async_turn_on(self, **kwargs) -> None:
        client = self.coordinator.client
        vehicle = self.vehicle
        action = self.entity_description.action
        if action == "climate":
            await client.async_set_climate(vehicle, True)
        elif action == "steering_wheel_heat":
            await client.async_set_steering_wheel_heat(vehicle, True)
        elif action == "front_defrost":
            await client.async_set_front_defrost(vehicle, True)
        elif action == "rear_defrost":
            await client.async_set_rear_defrost(vehicle, True)
        elif action == "seat_comfort_master":
            await client.async_set_seat_comfort_master(vehicle, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        client = self.coordinator.client
        vehicle = self.vehicle
        action = self.entity_description.action
        if action == "climate":
            await client.async_set_climate(vehicle, False)
        elif action == "steering_wheel_heat":
            await client.async_set_steering_wheel_heat(vehicle, False)
        elif action == "front_defrost":
            await client.async_set_front_defrost(vehicle, False)
        elif action == "rear_defrost":
            await client.async_set_rear_defrost(vehicle, False)
        elif action == "seat_comfort_master":
            await client.async_set_seat_comfort_master(vehicle, False)
        await self.coordinator.async_request_refresh()
