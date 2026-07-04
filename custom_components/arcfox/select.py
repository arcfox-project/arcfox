"""Select platform for ARCFOX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ArcfoxEntity


SEAT_OPTIONS: tuple[str, ...] = ("off", "level_1", "level_2", "level_3")


@dataclass(frozen=True, kw_only=True)
class ArcfoxSelectDescription(SelectEntityDescription):
    seat: str
    mode: str
    value_fn: Callable = lambda vehicle: None


SEATS: tuple[ArcfoxSelectDescription, ...] = (
    ArcfoxSelectDescription(
        key="left_front_seat_heat",
        translation_key="left_front_seat_heat",
        icon="mdi:car-seat",
        seat="left_front",
        mode="heat",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("left_front", "heat"),
    ),
    ArcfoxSelectDescription(
        key="right_front_seat_heat",
        translation_key="right_front_seat_heat",
        icon="mdi:car-seat",
        seat="right_front",
        mode="heat",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("right_front", "heat"),
    ),
    ArcfoxSelectDescription(
        key="left_back_seat_heat",
        translation_key="left_back_seat_heat",
        icon="mdi:car-seat",
        seat="left_back",
        mode="heat",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("left_back", "heat"),
    ),
    ArcfoxSelectDescription(
        key="right_back_seat_heat",
        translation_key="right_back_seat_heat",
        icon="mdi:car-seat",
        seat="right_back",
        mode="heat",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("right_back", "heat"),
    ),
    ArcfoxSelectDescription(
        key="left_front_seat_wind",
        translation_key="left_front_seat_wind",
        icon="mdi:car-seat",
        seat="left_front",
        mode="wind",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("left_front", "wind"),
    ),
    ArcfoxSelectDescription(
        key="right_front_seat_wind",
        translation_key="right_front_seat_wind",
        icon="mdi:car-seat",
        seat="right_front",
        mode="wind",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("right_front", "wind"),
    ),
    ArcfoxSelectDescription(
        key="left_back_seat_wind",
        translation_key="left_back_seat_wind",
        icon="mdi:car-seat",
        seat="left_back",
        mode="wind",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("left_back", "wind"),
    ),
    ArcfoxSelectDescription(
        key="right_back_seat_wind",
        translation_key="right_back_seat_wind",
        icon="mdi:car-seat",
        seat="right_back",
        mode="wind",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.seat_option("right_back", "wind"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ArcfoxSeatSelect] = []
    for vehicle_id in coordinator.data:
        entities.extend(
            ArcfoxSeatSelect(coordinator, vehicle_id, description) for description in SEATS
        )
    async_add_entities(entities)


class ArcfoxSeatSelect(ArcfoxEntity, SelectEntity):
    """ARCFOX seat option select."""

    entity_description: ArcfoxSelectDescription

    def __init__(self, coordinator, vehicle_id: str, description: ArcfoxSelectDescription) -> None:
        super().__init__(coordinator, vehicle_id)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle_id}_{description.key}"

    @property
    def current_option(self) -> str | None:
        return self.entity_description.value_fn(self.vehicle)

    @property
    def options(self) -> list[str]:
        return list(SEAT_OPTIONS)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.client.async_set_seat_option(
            self.vehicle,
            self.entity_description.seat,
            self.entity_description.mode,
            option,
        )
        await self.coordinator.async_request_refresh()
