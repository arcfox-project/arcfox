"""The ARCFOX integration."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ArcfoxApiClient
from .const import (
    COMMAND_TRANSPORT_HTTP,
    COMMAND_TRANSPORT_MQTT,
    COMMAND_TRANSPORT_APPSERVER,
    CONF_COMMAND_TRANSPORT,
    CONF_MQTT_CLIENT_ID,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_USE_TLS,
    CONF_MQTT_CERTFILE,
    CONF_MQTT_KEYFILE,
    CONF_MQTT_CAFILE,
    CONF_MQTT_USERNAME,
)
from .const import (
    CONF_BASE_URL,
    CONF_ACCESS_TOKEN,
    CONF_APP_TOKEN,
    CONF_REMOTE_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_REGION,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SECURITY_CODE,
    CONF_USER_ID,
    CONF_VIN,
    CONF_AID,
    CONF_IMEI,
    CONF_IOV_HOST,
    CONF_IOV_PORT,
    DEFAULT_BASE_URL,
    DEFAULT_IOV_HOST,
    DEFAULT_IOV_PORT,
    DEFAULT_REGION,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import ArcfoxDataUpdateCoordinator
from .protocol import COMMAND_SPECS
from .mqtt_client import ArcfoxMqttConfig, ArcfoxMqttPublisher
from .transport import ArcfoxBctpTransport, ArcfoxAppServerCommandTransport

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_COMMAND = "send_command"
DATA_ENTRIES = "entries"
DATA_SERVICES_REGISTERED = "services_registered"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("vehicle_id"): str,
        vol.Required("action"): vol.In(sorted(COMMAND_SPECS.keys())),
        vol.Optional("seat"): vol.In(("left_front", "right_front", "left_back", "right_back")),
        vol.Optional("mode"): vol.In(("heat", "wind")),
        vol.Optional("option"): str,
        vol.Optional("temperature"): vol.Coerce(float),
        vol.Optional("enabled", default=True): bool,
        vol.Optional("level", default=1): vol.All(int, vol.Range(min=0, max=3)),
    }
)


@dataclass(slots=True)
class ArcfoxRuntimeData:
    """Runtime objects stored for a config entry."""

    client: ArcfoxApiClient
    coordinator: ArcfoxDataUpdateCoordinator
    mqtt_publisher: ArcfoxMqttPublisher | None = None


type ArcfoxConfigEntry = ConfigEntry[ArcfoxRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: ArcfoxConfigEntry) -> bool:
    """Set up ARCFOX from a config entry."""
    session = async_get_clientsession(hass)
    mqtt_publisher: ArcfoxMqttPublisher | None = None
    config = dict(entry.data)
    config.update(entry.options)
    command_mode = config.get(CONF_COMMAND_TRANSPORT, COMMAND_TRANSPORT_HTTP)

    async def _persist_auth_state(auth_state: dict[str, Any]) -> None:
        result = hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, **auth_state},
        )
        if inspect.isawaitable(result):
            await result

    _LOGGER.warning("ARCFOX setup: creating client entry=%s", entry.entry_id)
    client = ArcfoxApiClient(
        session=session,
        base_url=config.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        user_id=config.get(CONF_USER_ID, config.get("username", "")),
        vin=config.get(CONF_VIN, config.get("vin", "")),
        region=config.get(CONF_REGION, DEFAULT_REGION),
        timeout=config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        access_token=config.get(CONF_ACCESS_TOKEN),
        app_token=config.get(CONF_APP_TOKEN),
        remote_token=config.get(CONF_REMOTE_TOKEN),
        password=config.get(CONF_PASSWORD),
        refresh_token=config.get(CONF_REFRESH_TOKEN),
        security_code=config.get(CONF_SECURITY_CODE),
        aid=config.get(CONF_AID),
        imei=config.get(CONF_IMEI),
        iov_host=config.get(CONF_IOV_HOST, DEFAULT_IOV_HOST),
        iov_port=int(config.get(CONF_IOV_PORT, DEFAULT_IOV_PORT)),
    )
    client.set_auth_state_callback(lambda auth_state: hass.async_create_task(_persist_auth_state(auth_state)))
    if command_mode == COMMAND_TRANSPORT_MQTT:
        mqtt_host = config.get(CONF_MQTT_HOST)
        if mqtt_host:
            mqtt_publisher = ArcfoxMqttPublisher(
                ArcfoxMqttConfig(
                    host=mqtt_host,
                    port=int(config.get(CONF_MQTT_PORT, 1883)),
                    username=config.get(CONF_MQTT_USERNAME),
                    password=config.get(CONF_MQTT_PASSWORD),
                    client_id=config.get(CONF_MQTT_CLIENT_ID),
                    use_tls=bool(config.get(CONF_MQTT_USE_TLS, False)),
                    certfile=config.get(CONF_MQTT_CERTFILE),
                    keyfile=config.get(CONF_MQTT_KEYFILE),
                    cafile=config.get(CONF_MQTT_CAFILE),
                )
            )
            client.set_command_transport(
                ArcfoxBctpTransport(
                    mqtt_publisher.publish,
                    token_getter=lambda: client.access_token or "",
                )
            )
    elif command_mode == COMMAND_TRANSPORT_APPSERVER:
        client.set_command_transport(
            ArcfoxAppServerCommandTransport(
                vin=config.get(CONF_VIN, ""),
                app_token=config.get(CONF_APP_TOKEN, ""),
                aid=str(config.get(CONF_AID, "")),
                imei=config.get(CONF_IMEI, ""),
                host=config.get(CONF_IOV_HOST, DEFAULT_IOV_HOST),
                port=int(config.get(CONF_IOV_PORT, DEFAULT_IOV_PORT)),
                timeout=config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            )
        )
    coordinator = ArcfoxDataUpdateCoordinator(hass, client, entry)
    _LOGGER.warning("ARCFOX setup: first refresh start entry=%s", entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.warning("ARCFOX setup: first refresh done entry=%s vehicles=%s", entry.entry_id, list(coordinator.data or {}))

    domain_data = hass.data.setdefault(DOMAIN, {})
    entries = domain_data.setdefault(DATA_ENTRIES, {})
    entries[entry.entry_id] = entry.runtime_data = ArcfoxRuntimeData(
        client=client,
        coordinator=coordinator,
        mqtt_publisher=mqtt_publisher,
    )
    if not domain_data.get(DATA_SERVICES_REGISTERED):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_COMMAND,
            _make_service_send_command_handler(hass),
            schema=SERVICE_SCHEMA,
        )
        domain_data[DATA_SERVICES_REGISTERED] = True

    _LOGGER.warning("ARCFOX setup: forwarding platforms entry=%s", entry.entry_id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.warning("ARCFOX setup: complete entry=%s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ArcfoxConfigEntry) -> bool:
    """Unload ARCFOX config entry."""
    if entry.runtime_data.mqtt_publisher is not None:
        await entry.runtime_data.mqtt_publisher.close()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    domain_data = hass.data.get(DOMAIN, {})
    entries = domain_data.get(DATA_ENTRIES, {})
    entries.pop(entry.entry_id, None)
    return unloaded


def _make_service_send_command_handler(hass: HomeAssistant):
    """Create a service handler bound to the current Home Assistant instance."""

    async def _async_service_send_command(call: Any) -> None:
        """Send a test command through the current ARCFOX transport."""
        domain_data = hass.data.get(DOMAIN, {})
        entries = domain_data.get(DATA_ENTRIES, {})
        vehicle_id = call.data["vehicle_id"]
        action = call.data["action"]
        matched_entry = None
        matched_vehicle = None
        for entry in entries.values():
            coordinator = entry.coordinator
            if vehicle_id in coordinator.data:
                matched_entry = entry
                matched_vehicle = coordinator.data[vehicle_id]
                break
        if matched_entry is None or matched_vehicle is None:
            raise ValueError(f"Unknown vehicle_id: {vehicle_id}")

        client = matched_entry.client
        if action == "lock":
            await client.async_set_lock(matched_vehicle, bool(call.data.get("enabled", True)))
        elif action == "unlock":
            await client.async_set_lock(matched_vehicle, False)
        elif action == "climate_on":
            await client.async_set_climate(matched_vehicle, True)
        elif action == "climate_off":
            await client.async_set_climate(matched_vehicle, False)
        elif action == "set_climate_temperature":
            await client.async_set_climate_temperature(
                matched_vehicle, float(call.data.get("temperature", 21.0))
            )
        elif action == "steering_wheel_heat_on":
            await client.async_set_steering_wheel_heat(matched_vehicle, True)
        elif action == "steering_wheel_heat_off":
            await client.async_set_steering_wheel_heat(matched_vehicle, False)
        elif action == "front_defrost_on":
            await client.async_set_front_defrost(matched_vehicle, True)
        elif action == "front_defrost_off":
            await client.async_set_front_defrost(matched_vehicle, False)
        elif action == "rear_defrost_on":
            await client.async_set_rear_defrost(matched_vehicle, True)
        elif action == "rear_defrost_off":
            await client.async_set_rear_defrost(matched_vehicle, False)
        elif action == "seat_comfort_master_on":
            await client.async_set_seat_comfort_master(matched_vehicle, True)
        elif action == "seat_comfort_master_off":
            await client.async_set_seat_comfort_master(matched_vehicle, False)
        elif action in {"seat_heat", "seat_wind"}:
            seat = call.data["seat"]
            mode = call.data.get("mode", "heat" if action == "seat_heat" else "wind")
            option = call.data.get("option")
            if option is None:
                level = int(call.data.get("level", 1))
                option = "off" if not bool(call.data.get("enabled", True)) else f"level_{level}"
            await client.async_set_seat_option(matched_vehicle, seat, mode, option)
        elif action == "wake_up":
            await client.async_wake_up(matched_vehicle)
        elif action == "window_open":
            await client.async_set_window(matched_vehicle, True)
        elif action == "window_close":
            await client.async_set_window(matched_vehicle, False)
        elif action == "sunroof_open":
            await client.async_set_sunroof(matched_vehicle, True)
        elif action == "sunroof_close":
            await client.async_set_sunroof(matched_vehicle, False)
        elif action == "trunk_open":
            await client.async_open_trunk(matched_vehicle)
        elif action == "flash_honk":
            await client.async_flash_honk(matched_vehicle)
        else:
            raise ValueError(f"Unsupported action: {action}")

        _LOGGER.debug(
            "ARCFOX service command sent: action=%s vehicle_id=%s vehicle_vin=%s",
            action,
            vehicle_id,
            matched_vehicle.vin,
        )

    return _async_service_send_command
