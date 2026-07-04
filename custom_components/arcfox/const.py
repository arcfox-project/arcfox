"""Constants for the ARCFOX integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "arcfox"
PLATFORMS: Final = (
    "sensor",
    "binary_sensor",
    "lock",
    "switch",
    "number",
    "select",
    "device_tracker",
    "button",
)

DEFAULT_NAME: Final = "ARCFOX"
DEFAULT_REGION: Final = "cn"
DEFAULT_BASE_URL: Final = "https://hbt-app-rsa-pre.bjev.com.cn"
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 5
DEFAULT_TIMEOUT: Final = 20

CONF_BASE_URL: Final = "base_url"
CONF_REGION: Final = "region"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_TIMEOUT: Final = "timeout"
CONF_USER_ID: Final = "user_id"
CONF_VIN: Final = "vin"
CONF_SMS_CODE: Final = "sms_code"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_COMMAND_TRANSPORT: Final = "command_transport"
CONF_MQTT_HOST: Final = "mqtt_host"
CONF_MQTT_PORT: Final = "mqtt_port"
CONF_MQTT_USERNAME: Final = "mqtt_username"
CONF_MQTT_PASSWORD: Final = "mqtt_password"
CONF_MQTT_CLIENT_ID: Final = "mqtt_client_id"
CONF_MQTT_USE_TLS: Final = "mqtt_use_tls"

COMMAND_TRANSPORT_HTTP: Final = "http"
COMMAND_TRANSPORT_MQTT: Final = "mqtt"

COORDINATOR_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)

ATTR_VIN: Final = "vin"
ATTR_MODEL: Final = "model"
ATTR_BRAND: Final = "brand"
