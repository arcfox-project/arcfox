"""Number platform for ARCFOX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ArcfoxEntity


@dataclass(frozen=True, kw_only=True)
class ArcfoxNumberDescription(NumberEntityDescription):
    value_fn: Callable = lambda vehicle: None


NUMBERS: tuple[ArcfoxNumberDescription, ...] = (
    ArcfoxNumberDescription(
        key="climate_target_temp",
        translation_key="climate_target_temp",
        icon="mdi:thermometer",
        native_min_value=16,
        native_max_value=30,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda vehicle: vehicle.climate_target_c,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ArcfoxNumber] = []
    for vehicle_id in coordinator.data:
        entities.extend(
            ArcfoxNumber(coordinator, vehicle_id, description) for description in NUMBERS
        )
    async_add_entities(entities)


class ArcfoxNumber(ArcfoxEntity, NumberEntity):
    """ARCFOX number entity."""

    entity_description: ArcfoxNumberDescription

    def __init__(self, coordinator, vehicle_id: str, description: ArcfoxNumberDescription) -> None:
        super().__init__(coordinator, vehicle_id)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle_id}_{description.key}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.vehicle)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_set_climate_temperature(
            self.vehicle.vehicle_id,
            value,
        )
        await self.coordinator.async_request_refresh()
