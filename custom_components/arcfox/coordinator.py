"""Data coordinator for ARCFOX."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArcfoxApiClient, ArcfoxApiError, ArcfoxAuthError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES, DOMAIN
from .models import ArcfoxVehicle

_LOGGER = logging.getLogger(__name__)


class ArcfoxDataUpdateCoordinator(DataUpdateCoordinator[dict[str, ArcfoxVehicle]]):
    """Coordinate ARCFOX vehicle state refreshes."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: ArcfoxApiClient,
        config_entry: ConfigEntry,
    ) -> None:
        self.client = client
        self.config_entry = config_entry
        interval = timedelta(
            minutes=config_entry.options.get(
                CONF_SCAN_INTERVAL,
                config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
        )

    async def _async_update_data(self) -> dict[str, ArcfoxVehicle]:
        _LOGGER.warning("ARCFOX coordinator refresh start entry=%s", self.config_entry.entry_id)
        try:
            vehicles = await self.client.async_get_vehicles()
        except ArcfoxAuthError as err:
            raise ConfigEntryAuthFailed from err
        except ArcfoxApiError as err:
            raise UpdateFailed(str(err)) from err

        result = {vehicle.vehicle_id: vehicle for vehicle in vehicles}
        _LOGGER.warning("ARCFOX coordinator refresh done entry=%s vehicles=%s", self.config_entry.entry_id, list(result))
        return result
