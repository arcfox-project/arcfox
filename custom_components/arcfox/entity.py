"""Shared ARCFOX entity helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_BRAND, ATTR_MODEL, ATTR_VIN, DOMAIN
from .coordinator import ArcfoxDataUpdateCoordinator
from .models import ArcfoxVehicle


class ArcfoxEntity(CoordinatorEntity[ArcfoxDataUpdateCoordinator]):
    """Base entity for ARCFOX vehicles."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ArcfoxDataUpdateCoordinator,
        vehicle_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._vehicle_id = vehicle_id

    @property
    def vehicle(self) -> ArcfoxVehicle:
        """Return the current normalized vehicle snapshot."""
        return self.coordinator.data[self._vehicle_id]

    @property
    def available(self) -> bool:
        return super().available and self._vehicle_id in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        vehicle = self.vehicle
        return DeviceInfo(
            identifiers={(DOMAIN, vehicle.vehicle_id)},
            name=vehicle.name,
            manufacturer=vehicle.brand or "ARCFOX",
            model=vehicle.model,
            serial_number=vehicle.vin,
            suggested_area="Garage",
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | float | bool | None]:
        vehicle = self.vehicle
        client = self.coordinator.client
        raw_keys = sorted(vehicle.raw.keys())
        status_keys = []
        for key in ("status", "vehicleState", "vehicleStatus", "vehicleInfo", "vehicleData"):
            value = vehicle.raw.get(key)
            if isinstance(value, dict):
                status_keys = sorted(value.keys())
                break
        return {
            ATTR_VIN: vehicle.vin,
            ATTR_MODEL: vehicle.model,
            ATTR_BRAND: vehicle.brand,
            "arcfox_state_wt": (vehicle.raw.get("raw") or {}).get("WT"),
            "battery_pct": vehicle.battery_pct,
            "range_km": vehicle.range_km,
            "odometer_km": vehicle.odometer_km,
            "climate_target_c": vehicle.climate_target_c,
            "steering_wheel_heat_on": vehicle.steering_wheel_heat_on,
            "front_defrost_on": vehicle.front_defrost_on,
            "rear_defrost_on": vehicle.rear_defrost_on,
            "arcfox_connection_source": vehicle.raw.get("arcfox_connection_source"),
            "arcfox_last_request_path": client.last_request_path,
            "arcfox_last_success_path": client.last_success_path,
            "arcfox_last_error": client.last_error,
            "arcfox_authenticated": bool(client.access_token),
            "arcfox_account_id": client.account_id,
            "arcfox_raw_keys": ",".join(raw_keys[:40]),
            "arcfox_status_keys": ",".join(status_keys[:40]) if status_keys else None,
        }
