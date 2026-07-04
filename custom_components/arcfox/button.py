"""Button platform for ARCFOX."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ArcfoxEntity


@dataclass(frozen=True, kw_only=True)
class ArcfoxButtonDescription(ButtonEntityDescription):
    action: str


BUTTONS: tuple[ArcfoxButtonDescription, ...] = (
    ArcfoxButtonDescription(
        key="wake_up",
        translation_key="wake_up",
        icon="mdi:car-connected",
        action="wake_up",
    ),
    ArcfoxButtonDescription(
        key="window_open",
        translation_key="window_open",
        icon="mdi:car-window-open",
        action="window_open",
    ),
    ArcfoxButtonDescription(
        key="window_close",
        translation_key="window_close",
        icon="mdi:car-window-closed",
        action="window_close",
    ),
    ArcfoxButtonDescription(
        key="sunroof_open",
        translation_key="sunroof_open",
        icon="mdi:car-sunroof",
        action="sunroof_open",
    ),
    ArcfoxButtonDescription(
        key="sunroof_close",
        translation_key="sunroof_close",
        icon="mdi:car-sunroof",
        action="sunroof_close",
    ),
    ArcfoxButtonDescription(
        key="trunk_open",
        translation_key="trunk_open",
        icon="mdi:car-back",
        action="trunk_open",
    ),
    ArcfoxButtonDescription(
        key="flash_honk",
        translation_key="flash_honk",
        icon="mdi:bullhorn",
        action="flash_honk",
    ),
    ArcfoxButtonDescription(
        key="refresh",
        translation_key="refresh",
        icon="mdi:refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        action="refresh",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ArcfoxButton] = []
    for vehicle_id in coordinator.data:
        entities.extend(ArcfoxButton(coordinator, vehicle_id, description) for description in BUTTONS)
    async_add_entities(entities)


class ArcfoxButton(ArcfoxEntity, ButtonEntity):
    """ARCFOX button entity."""

    entity_description: ArcfoxButtonDescription

    def __init__(self, coordinator, vehicle_id: str, description: ArcfoxButtonDescription) -> None:
        super().__init__(coordinator, vehicle_id)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle_id}_{description.key}"

    async def async_press(self) -> None:
        action = self.entity_description.action
        client = self.coordinator.client
        vehicle = self.vehicle
        if action == "wake_up":
            await client.async_wake_up(vehicle)
        elif action == "window_open":
            await client.async_set_window(vehicle, True)
        elif action == "window_close":
            await client.async_set_window(vehicle, False)
        elif action == "sunroof_open":
            await client.async_set_sunroof(vehicle, True)
        elif action == "sunroof_close":
            await client.async_set_sunroof(vehicle, False)
        elif action == "trunk_open":
            await client.async_open_trunk(vehicle)
        elif action == "flash_honk":
            await client.async_flash_honk(vehicle)
        await self.coordinator.async_request_refresh()
