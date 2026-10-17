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
DEFAULT_BASE_URL: Final = "https://hbt-app-rsa.bjev.com.cn"
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 5
DEFAULT_TIMEOUT: Final = 20
DEFAULT_IOV_HOST: Final = "arcfoxapp-new-iov.bjev.com.cn"

# Public OAuth client credentials embedded in the official ARCFOX App
# (BuildConfig.HBT_APPID / HBT_SECRET).  They are used to obtain the
# short-lived application token required for B2C account login and token
# refresh and are not user account secrets.
B2C_OAUTH_CLIENT_ID: Final = 7
B2C_OAUTH_CLIENT_SECRET: Final = "FDxD9DxDJTsaT3uS8keTbt2HUEcmxH82"
B2C_OAUTH_SCOPES: Final = (
    "viam_va_nologin_management",
    "vcbs_push_send",
    "viam_auth_token",
    "viam_va_base_query",
    "viam_auth_social",
)
DEFAULT_IOV_PORT: Final = 60115

CONF_BASE_URL: Final = "base_url"
CONF_REGION: Final = "region"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_APP_TOKEN: Final = "app_token"
CONF_REMOTE_TOKEN: Final = "remote_token"
CONF_PASSWORD: Final = "password"
CONF_TIMEOUT: Final = "timeout"
CONF_USER_ID: Final = "user_id"
CONF_VIN: Final = "vin"
CONF_AID: Final = "aid"
CONF_IMEI: Final = "imei"
CONF_IOV_HOST: Final = "iov_host"
CONF_IOV_PORT: Final = "iov_port"
CONF_SMS_CODE: Final = "sms_code"
CONF_CAPTCHA_CODE: Final = "captcha_code"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_SECURITY_CODE: Final = "security_code"
CONF_COMMAND_TRANSPORT: Final = "command_transport"
CONF_MQTT_HOST: Final = "mqtt_host"
CONF_MQTT_PORT: Final = "mqtt_port"
CONF_MQTT_USERNAME: Final = "mqtt_username"
CONF_MQTT_PASSWORD: Final = "mqtt_password"
CONF_MQTT_CLIENT_ID: Final = "mqtt_client_id"
CONF_MQTT_USE_TLS: Final = "mqtt_use_tls"
CONF_MQTT_CERTFILE: Final = "mqtt_certfile"
CONF_MQTT_KEYFILE: Final = "mqtt_keyfile"
CONF_MQTT_CAFILE: Final = "mqtt_cafile"

COMMAND_TRANSPORT_HTTP: Final = "http"
COMMAND_TRANSPORT_MQTT: Final = "mqtt"
COMMAND_TRANSPORT_APPSERVER: Final = "appserver"

COORDINATOR_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)

ATTR_VIN: Final = "vin"
ATTR_MODEL: Final = "model"
ATTR_BRAND: Final = "brand"
