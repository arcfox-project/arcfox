"""Config flow for ARCFOX."""

from __future__ import annotations

from typing import Any

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ArcfoxApiClient, ArcfoxApiError, ArcfoxAuthError
from .const import (
    COMMAND_TRANSPORT_HTTP,
    COMMAND_TRANSPORT_MQTT,
    CONF_ACCOUNT_ID,
    CONF_ACCESS_TOKEN,
    CONF_APP_TOKEN,
    CONF_BASE_URL,
    CONF_COMMAND_TRANSPORT,
    CONF_MQTT_CLIENT_ID,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_USE_TLS,
    CONF_MQTT_USERNAME,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SECURITY_CODE,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SMS_CODE,
    CONF_TIMEOUT,
    CONF_USER_ID,
    CONF_VIN,
    DEFAULT_BASE_URL,
    DEFAULT_REGION,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


USER_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USER_ID): str,
        vol.Optional(CONF_VIN): str,
        vol.Optional(CONF_ACCESS_TOKEN): str,
        vol.Optional(CONF_REFRESH_TOKEN): str,
        vol.Optional(CONF_SECURITY_CODE): str,
        vol.Optional(CONF_APP_TOKEN): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
        vol.Optional(CONF_REGION, default=DEFAULT_REGION): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL_MINUTES): vol.All(
            int, vol.Range(min=1, max=60)
        ),
        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
            int, vol.Range(min=5, max=120)
        ),
        vol.Optional(CONF_COMMAND_TRANSPORT, default=COMMAND_TRANSPORT_HTTP): vol.In(
            [COMMAND_TRANSPORT_HTTP, COMMAND_TRANSPORT_MQTT]
        ),
        vol.Optional(CONF_MQTT_HOST): str,
        vol.Optional(CONF_MQTT_PORT, default=1883): vol.All(int, vol.Range(min=1, max=65535)),
        vol.Optional(CONF_MQTT_USERNAME): str,
        vol.Optional(CONF_MQTT_PASSWORD): str,
        vol.Optional(CONF_MQTT_CLIENT_ID): str,
        vol.Optional(CONF_MQTT_USE_TLS, default=False): bool,
    }
)

SMS_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SMS_CODE): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BASE_URL): str,
        vol.Optional(CONF_SCAN_INTERVAL): vol.All(int, vol.Range(min=1, max=60)),
        vol.Optional(CONF_TIMEOUT): vol.All(int, vol.Range(min=5, max=120)),
        vol.Optional(CONF_COMMAND_TRANSPORT): vol.In(
            [COMMAND_TRANSPORT_HTTP, COMMAND_TRANSPORT_MQTT]
        ),
        vol.Optional(CONF_MQTT_HOST): str,
        vol.Optional(CONF_MQTT_PORT): vol.All(int, vol.Range(min=1, max=65535)),
        vol.Optional(CONF_MQTT_USERNAME): str,
        vol.Optional(CONF_MQTT_PASSWORD): str,
        vol.Optional(CONF_MQTT_CLIENT_ID): str,
        vol.Optional(CONF_MQTT_USE_TLS): bool,
        vol.Optional(CONF_SECURITY_CODE): str,
    }
)


def _build_client(hass, data: dict[str, Any], sms_code: str | None = None) -> ArcfoxApiClient:
    """Create an API client for validation or login."""
    if data.get(CONF_COMMAND_TRANSPORT, COMMAND_TRANSPORT_HTTP) == COMMAND_TRANSPORT_MQTT:
        if not data.get(CONF_MQTT_HOST):
            raise ArcfoxApiError("Missing MQTT host for command transport")
    return ArcfoxApiClient(
        session=async_get_clientsession(hass),
        base_url=data[CONF_BASE_URL],
        user_id=data[CONF_USER_ID],
        vin=data.get(CONF_VIN, ""),
        region=data[CONF_REGION],
        timeout=data[CONF_TIMEOUT],
        access_token=data.get(CONF_ACCESS_TOKEN),
        app_token=data.get(CONF_APP_TOKEN),
        password=data.get(CONF_PASSWORD),
        sms_code=sms_code,
        refresh_token=data.get(CONF_REFRESH_TOKEN),
        security_code=data.get(CONF_SECURITY_CODE),
        command_transport=None,
    )


async def _request_sms_code(hass, data: dict[str, Any]) -> None:
    """Trigger an SMS code request."""
    client = _build_client(hass, data)
    await client.async_request_sms_code()


async def _validate_input(
    hass,
    data: dict[str, Any],
) -> tuple[str, str, str | None, str]:
    """Validate user input against the remote API."""
    client = _build_client(hass, data, sms_code=data[CONF_SMS_CODE])
    if data.get(CONF_ACCESS_TOKEN) or data.get(CONF_REFRESH_TOKEN) or data.get(CONF_PASSWORD):
        try:
            vehicles = await client.async_test_connection()
        except Exception:
            _LOGGER.exception("ARCFOX token validation failed")
            raise
        account_id = client.account_id or data[CONF_USER_ID].strip().lower()
        title = vehicles[0].name if vehicles else data.get(CONF_VIN) or account_id
        return account_id, title, client.access_token or None, client.refresh_token or ""
    try:
        vehicles = await client.async_test_connection()
    except Exception:
        _LOGGER.exception("ARCFOX config validation failed")
        raise
    title = vehicles[0].name if vehicles else data[CONF_USER_ID]
    account_id = data[CONF_USER_ID].strip().lower()
    access_token = client.access_token or ""
    refresh_token = client.refresh_token or ""
    return account_id, title, access_token or None, refresh_token


class ArcfoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an ARCFOX config flow."""

    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self._pending_user_input: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                if (
                    user_input.get(CONF_ACCESS_TOKEN)
                    or user_input.get(CONF_REFRESH_TOKEN)
                    or user_input.get(CONF_PASSWORD)
                ):
                    account_id, title, access_token, refresh_token = await _validate_input(
                        self.hass,
                        {**user_input, CONF_SMS_CODE: user_input.get(CONF_SMS_CODE, "")},
                    )
                    await self.async_set_unique_id(account_id)
                    self._abort_if_unique_id_configured()

                    stored = dict(user_input)
                    # Password and app token only bootstrap a B2C session; keep
                    # the returned user/refresh tokens, not the credentials.
                    stored.pop(CONF_PASSWORD, None)
                    stored.pop(CONF_APP_TOKEN, None)
                    if not stored.get(CONF_VIN):
                        stored.pop(CONF_VIN, None)
                    stored[CONF_ACCOUNT_ID] = account_id
                    if access_token:
                        stored[CONF_ACCESS_TOKEN] = access_token
                    if refresh_token:
                        stored[CONF_REFRESH_TOKEN] = refresh_token
                    return self.async_create_entry(title=title, data=stored)
                await _request_sms_code(self.hass, user_input)
            except ArcfoxAuthError:
                errors["base"] = "invalid_auth"
            except ArcfoxApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                self._pending_user_input = dict(user_input)
                return await self.async_step_sms()

        return self.async_show_form(
            step_id="user",
            data_schema=USER_STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_sms(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            if self._pending_user_input is None:
                errors["base"] = "unknown"
            else:
                data = dict(self._pending_user_input)
                data.update(user_input)
                try:
                    account_id, title, access_token, refresh_token = await _validate_input(
                        self.hass, data
                    )
                except ArcfoxAuthError:
                    errors["base"] = "invalid_auth"
                except ArcfoxApiError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(account_id)
                    self._abort_if_unique_id_configured()

                    stored = dict(self._pending_user_input)
                    stored.pop(CONF_SMS_CODE, None)
                    stored.pop(CONF_PASSWORD, None)
                    stored.pop(CONF_APP_TOKEN, None)
                    stored[CONF_ACCOUNT_ID] = account_id
                    if not stored.get(CONF_VIN):
                        stored.pop(CONF_VIN, None)
                    if access_token:
                        stored[CONF_ACCESS_TOKEN] = access_token
                    if refresh_token:
                        stored[CONF_REFRESH_TOKEN] = refresh_token
                    return self.async_create_entry(title=title, data=stored)

        return self.async_show_form(
            step_id="sms",
            data_schema=SMS_STEP_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return ArcfoxOptionsFlow(config_entry)


class ArcfoxOptionsFlow(config_entries.OptionsFlow):
    """Handle ARCFOX options."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {
            CONF_BASE_URL: self._config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            CONF_SCAN_INTERVAL: self._config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self._config_entry.data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                ),
            ),
            CONF_TIMEOUT: self._config_entry.options.get(
                CONF_TIMEOUT,
                self._config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            ),
            CONF_COMMAND_TRANSPORT: self._config_entry.data.get(
                CONF_COMMAND_TRANSPORT, COMMAND_TRANSPORT_HTTP
            ),
            CONF_MQTT_HOST: self._config_entry.data.get(CONF_MQTT_HOST),
            CONF_MQTT_PORT: self._config_entry.data.get(CONF_MQTT_PORT, 1883),
            CONF_MQTT_USERNAME: self._config_entry.data.get(CONF_MQTT_USERNAME),
            CONF_MQTT_PASSWORD: self._config_entry.data.get(CONF_MQTT_PASSWORD),
            CONF_MQTT_CLIENT_ID: self._config_entry.data.get(CONF_MQTT_CLIENT_ID),
            CONF_MQTT_USE_TLS: self._config_entry.data.get(CONF_MQTT_USE_TLS, False),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, options),
        )
