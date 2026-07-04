"""HTTP client for ARCFOX cloud APIs."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from aiohttp import ClientSession

from .protocol import (
    ArcfoxCommandPayload,
    COMMAND_SPECS,
    build_cmd2_temperature_payload,
    build_cmd8_seat_payload,
)
from .models import ArcfoxVehicle
from .transport import (
    ArcfoxHttpTransport,
    ArcfoxCommandTransport,
    ArcfoxTransport,
    ArcfoxTransportAuthError,
    ArcfoxTransportError,
)


class ArcfoxApiError(Exception):
    """Base API error."""


class ArcfoxAuthError(ArcfoxApiError):
    """Authentication error."""


_LOGGER = logging.getLogger(__name__)


def _build_base_url_candidates(base_url: str) -> list[str]:
    """Build a small ordered set of API base URL candidates."""
    normalized = base_url.rstrip("/")
    candidates = [normalized]
    parsed = urlsplit(normalized)
    if parsed.scheme and parsed.netloc:
        host_root = f"{parsed.scheme}://{parsed.netloc}"
        host_api = f"{host_root}/api"
        for candidate in (
            "https://hbt-app-rsa-pre.bjev.com.cn",
            "https://hbt-app-rsa-pre.bjev.com.cn/api",
            "https://hbt-app-rsa.bjev.com.cn",
            "https://hbt-app-rsa.bjev.com.cn/api",
            host_root,
            host_api,
            "https://napi.arcfox.cn",
            "https://napi.arcfox.cn/api",
            "https://arcfoxapp-new-iov.bjev.com.cn",
            "https://arcfoxapp-new-iov.bjev.com.cn/api",
        ):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


class ArcfoxApiClient:
    """Client for ARCFOX cloud APIs.

    The endpoint paths are intentionally isolated here because public official API
    documentation is not available. Replace the placeholders with real mobile-app
    endpoints once traffic samples are available.
    """

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        user_id: str,
        vin: str,
        region: str,
        timeout: int,
        access_token: str | None = None,
        sms_code: str | None = None,
        refresh_token: str | None = None,
        command_transport: ArcfoxCommandTransport | None = None,
        auth_state_callback: Any | None = None,
    ) -> None:
        self._user_id = user_id
        self._vin = vin
        self._region = region
        self._sms_code = sms_code
        self._access_token: str | None = access_token or None
        self._refresh_token: str | None = refresh_token
        self._account_id: str | None = None
        self._auth_data: dict[str, Any] | None = None
        self._last_request_path: str | None = None
        self._last_success_path: str | None = None
        self._last_error: str | None = None
        self._transport: ArcfoxTransport = ArcfoxHttpTransport(
            session,
            _build_base_url_candidates(base_url),
            timeout,
        )
        self._command_transport = command_transport
        self._auth_state_callback = auth_state_callback

    @property
    def account_id(self) -> str | None:
        """Return the resolved remote account ID."""
        return self._account_id

    @property
    def access_token(self) -> str | None:
        """Return the current access token."""
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        """Return the current refresh token."""
        return self._refresh_token

    @property
    def last_request_path(self) -> str | None:
        """Return the most recent API path attempted."""
        return self._last_request_path

    @property
    def last_success_path(self) -> str | None:
        """Return the most recent API path that returned successfully."""
        return self._last_success_path

    @property
    def last_error(self) -> str | None:
        """Return the most recent transport/API error."""
        return self._last_error

    def set_command_transport(self, command_transport: ArcfoxCommandTransport | None) -> None:
        """Attach or replace the command transport."""
        self._command_transport = command_transport

    def set_auth_state_callback(self, callback: Any | None) -> None:
        """Attach a callback that persists refreshed auth state."""
        self._auth_state_callback = callback

    async def async_authenticate(self) -> str:
        """Authenticate and store the bearer token."""
        if self._access_token:
            return self._account_id or self._vin

        if self._refresh_token and not self._sms_code:
            _LOGGER.debug(
                "ARCFOX authenticating with refresh token for vin=%s user_id=%s",
                self._vin,
                self._user_id,
            )
            return await self.async_refresh_access_token()

        if not self._sms_code:
            raise ArcfoxAuthError("Missing SMS code for ARCFOX login")

        _LOGGER.debug(
            "ARCFOX authenticating with vin=%s user_id=%s region=%s",
            self._vin,
            self._user_id,
            self._region,
        )
        payload = {
            "userId": self._user_id,
            "smsCode": self._sms_code,
        }
        if self._vin:
            payload["vin"] = self._vin
        data = await self._request("post", "/auth/signin", json=payload)
        self._store_auth_data(data)
        return self._account_id or self._vin

    async def async_request_sms_code(self) -> None:
        """Request an SMS verification code for login."""
        _LOGGER.debug(
            "ARCFOX requesting SMS code for vin=%s user_id=%s",
            self._vin,
            self._user_id,
        )
        payload = {
            "userId": self._user_id,
        }
        if self._vin:
            payload["vin"] = self._vin
        data = await self._request("post", "/auth/signinsms", json=payload)
        self._auth_data = data

    async def async_refresh_access_token(self) -> str:
        """Refresh the current access token using the stored refresh token."""
        if not self._refresh_token:
            raise ArcfoxAuthError("Missing refresh token for ARCFOX login")

        _LOGGER.debug(
            "ARCFOX refreshing access token for vin=%s user_id=%s",
            self._vin,
            self._user_id,
        )
        payload = {
            "refreshToken": self._refresh_token,
        }
        if self._vin:
            payload["vin"] = self._vin
        data = await self._request("post", "/auth/refreshtoken", json=payload)
        self._store_auth_data(data)
        return self._account_id or self._vin

    async def async_test_connection(self) -> list[ArcfoxVehicle]:
        """Validate credentials and return available vehicles."""
        await self._ensure_authenticated()
        return await self.async_get_vehicles()

    async def async_get_vehicles(self) -> list[ArcfoxVehicle]:
        """Fetch all vehicles associated with the account."""
        await self._ensure_authenticated()
        vehicle_items: list[dict[str, Any]] = []

        if self._vin:
            payload: dict[str, Any] = {"vin": self._vin, "vehicleId": self._vin}
            config_payload = None
            status = None
            try:
                config_payload = await self._request("get", f"/tsp/car/vehicleConfig/{self._vin}")
            except ArcfoxApiError:
                config_payload = None
            try:
                status = await self.async_get_vehicle_status(self._vin)
            except ArcfoxApiError:
                status = None
            if isinstance(config_payload, dict):
                payload = {**payload, **config_payload}
            if config_payload is not None or status is not None:
                payload["arcfox_connection_source"] = (
                    "vehicle_config+car_state"
                    if status is not None and config_payload is not None
                    else "vehicle_config"
                    if config_payload is not None
                    else "car_state"
                )
                return [ArcfoxVehicle.from_payload(payload, status)]

            auth_items = self._extract_items(self._auth_data or {})
            if not auth_items and self._auth_data:
                candidate = self._extract_vehicle_candidate(self._auth_data)
                if candidate is not None:
                    auth_items = [candidate]
            if auth_items:
                auth_payload = auth_items[0]
                if isinstance(auth_payload, dict):
                    auth_payload = {
                        **auth_payload,
                        "vehicleId": auth_payload.get("vehicleId") or self._vin,
                        "vin": auth_payload.get("vin") or self._vin,
                        "arcfox_connection_source": "auth_response",
                    }
                    _LOGGER.warning(
                        "ARCFOX vehicle lookup for VIN %s fell back to auth response fields",
                        self._vin,
                    )
                    return [ArcfoxVehicle.from_payload(auth_payload)]

            _LOGGER.warning(
                "ARCFOX vehicle lookup returned no config/status/auth vehicle for VIN %s; using minimal vehicle stub",
                self._vin,
            )
            return [
                ArcfoxVehicle.from_payload(
                    {
                        "vehicleId": self._vin,
                        "vin": self._vin,
                        "vehicleName": self._vin,
                        "arcfox_connection_source": "stub",
                    }
                )
            ]

        vehicle_list_payload: dict[str, Any] | None = None
        try:
            vehicle_list_payload = await self._request(
                "get",
                f"/tsp/userAccount/findBindUserList/{self._user_id}",
            )
        except ArcfoxAuthError:
            if self._vin:
                raise
            _LOGGER.info(
                "ARCFOX vehicle list lookup unauthorized for user_id=%s; continuing with token-only setup",
                self._user_id,
            )
        except ArcfoxApiError:
            vehicle_list_payload = None

        vehicle_items = self._extract_items(vehicle_list_payload or {})
        if vehicle_items:
            vehicles: list[ArcfoxVehicle] = []
            for item in vehicle_items:
                if not isinstance(item, dict):
                    continue
                vehicle_id = str(item.get("vehicleId") or item.get("vin") or item.get("id") or "")
                config_payload = None
                status = None
                if vehicle_id:
                    try:
                        config_payload = await self._request("get", f"/tsp/car/vehicleConfig/{vehicle_id}")
                    except ArcfoxAuthError:
                        raise
                    except ArcfoxApiError:
                        config_payload = None
                    try:
                        status = await self.async_get_vehicle_status(vehicle_id)
                    except ArcfoxAuthError:
                        raise
                    except ArcfoxApiError:
                        status = None
                payload = {**item}
                if isinstance(config_payload, dict):
                    payload = {**payload, **config_payload}
                payload["arcfox_connection_source"] = (
                    "vehicle_list+vehicle_config+car_state"
                    if config_payload is not None and status is not None
                    else "vehicle_list+vehicle_config"
                    if config_payload is not None
                    else "vehicle_list+car_state"
                    if status is not None
                    else "vehicle_list"
                )
                vehicles.append(ArcfoxVehicle.from_payload(payload, status))
            return vehicles

        vehicle_items = self._extract_items(self._auth_data or {})
        if not vehicle_items and self._auth_data:
            candidate = self._extract_vehicle_candidate(self._auth_data)
            if candidate is not None:
                vehicle_items = [candidate]
        if not vehicle_items:
            _LOGGER.debug("ARCFOX login response did not include vehicle records; returning empty list")
            return []

        vehicles: list[ArcfoxVehicle] = []
        for item in vehicle_items:
            if not isinstance(item, dict):
                continue
            vehicle_id = str(item.get("vehicleId") or item.get("id") or item.get("vin") or "")
            config_payload = None
            status = None
            if vehicle_id:
                try:
                    config_payload = await self._request("get", f"/tsp/car/vehicleConfig/{vehicle_id}")
                except ArcfoxAuthError:
                    raise
                except ArcfoxApiError:
                    config_payload = None
                try:
                    status = await self.async_get_vehicle_status(vehicle_id)
                except ArcfoxAuthError:
                    raise
                except ArcfoxApiError:
                    status = None
            payload = {**item}
            if isinstance(config_payload, dict):
                payload = {**payload, **config_payload}
            payload["arcfox_connection_source"] = (
                "auth_response+vehicle_config+car_state"
                if config_payload is not None and status is not None
                else "auth_response+vehicle_config"
                if config_payload is not None
                else "auth_response+car_state"
                if status is not None
                else "auth_response"
            )
            vehicles.append(ArcfoxVehicle.from_payload(payload, status))

        return vehicles

    async def async_get_vehicle_status(self, vehicle_id: str) -> dict[str, Any]:
        """Fetch the status for a single vehicle."""
        await self._ensure_authenticated()
        candidates = (
            f"/rc/bctp/carState/query/{vehicle_id}",
            f"/rc/battery/info/{vehicle_id}",
            f"/rc/battery/info?vehicleId={vehicle_id}",
        )
        last_error: Exception | None = None
        for path in candidates:
            _LOGGER.debug("ARCFOX probing vehicle status path: %s", path)
            try:
                data = await self._request("get", path)
            except ArcfoxApiError as err:
                last_error = err
                continue

            if isinstance(data.get("data"), dict):
                return data["data"]
            if isinstance(data.get("data"), list) and data["data"]:
                first_item = data["data"][0]
                if isinstance(first_item, dict):
                    return first_item
            if isinstance(data, list) and data:
                first_item = data[0]
                if isinstance(first_item, dict):
                    return first_item
            if isinstance(data, dict) and any(
                key in data
                for key in (
                    "soc",
                    "kmTotal",
                    "limitedDriving",
                    "current",
                    "chargingleft",
                    "vehicleState",
                    "status",
                    "battery",
                )
            ):
                return data

        if last_error is not None:
            raise last_error
        raise ArcfoxApiError("ARCFOX vehicle status request returned no usable payload")

    async def async_set_lock(self, vehicle_id: ArcfoxVehicle | str, locked: bool) -> None:
        """Lock or unlock the vehicle."""
        await self._send_spec_command(vehicle_id, "lock" if locked else "unlock")

    async def async_set_climate(self, vehicle_id: ArcfoxVehicle | str, enabled: bool) -> None:
        """Enable or disable remote climate."""
        action = "climate_on" if enabled else "climate_off"
        await self._send_spec_command(vehicle_id, action, enabled)

    async def async_set_climate_temperature(self, vehicle_id: ArcfoxVehicle | str, temperature: float) -> None:
        """Set the remote climate target temperature."""
        await self._send_spec_command(vehicle_id, "set_climate_temperature", temperature)

    async def async_set_steering_wheel_heat(self, vehicle_id: ArcfoxVehicle | str, enabled: bool) -> None:
        """Enable or disable steering wheel heat."""
        action = "steering_wheel_heat_on" if enabled else "steering_wheel_heat_off"
        await self._send_spec_command(vehicle_id, action, enabled)

    async def async_set_front_defrost(self, vehicle_id: ArcfoxVehicle | str, enabled: bool) -> None:
        """Enable or disable front defrost."""
        action = "front_defrost_on" if enabled else "front_defrost_off"
        await self._send_spec_command(vehicle_id, action, enabled)

    async def async_set_rear_defrost(self, vehicle_id: ArcfoxVehicle | str, enabled: bool) -> None:
        """Enable or disable rear defrost."""
        action = "rear_defrost_on" if enabled else "rear_defrost_off"
        await self._send_spec_command(vehicle_id, action, enabled)

    async def async_set_seat_option(
        self,
        vehicle_id: ArcfoxVehicle | str,
        seat: str,
        mode: str,
        option: str,
    ) -> None:
        """Set a seat heat or ventilation option."""
        option_mode, _, level_text = option.partition("_")
        try:
            level = int(level_text)
        except ValueError:
            level = 0
        payload = build_cmd8_seat_payload(seat, level, enabled=option != "off").to_dict()
        action = "seat_heat" if mode == "heat" else "seat_wind"
        await self._send_command(
            vehicle_id,
            action,
            json={
                **payload,
                "seat": seat,
                "option": option,
                "requested_mode": mode,
                "option_mode": option_mode,
                "level": level,
            },
        )

    async def async_set_seat_comfort_master(self, vehicle_id: ArcfoxVehicle | str, enabled: bool) -> None:
        """Enable or disable the seat heat / wind master control."""
        action = "seat_comfort_master_on" if enabled else "seat_comfort_master_off"
        await self._send_spec_command(vehicle_id, action, enabled)

    async def async_open_trunk(self, vehicle_id: ArcfoxVehicle | str) -> None:
        """Open the trunk."""
        await self._send_spec_command(vehicle_id, "trunk_open", True)

    async def async_flash_honk(self, vehicle_id: ArcfoxVehicle | str) -> None:
        """Flash lights and honk the horn."""
        await self._send_spec_command(vehicle_id, "flash_honk", True)

    async def async_set_window(self, vehicle_id: ArcfoxVehicle | str, enabled: bool) -> None:
        """Open or close the window."""
        action = "window_open" if enabled else "window_close"
        await self._send_spec_command(vehicle_id, action, enabled)

    async def async_set_sunroof(self, vehicle_id: ArcfoxVehicle | str, enabled: bool) -> None:
        """Open or close the sunroof."""
        action = "sunroof_open" if enabled else "sunroof_close"
        await self._send_spec_command(vehicle_id, action, enabled)

    async def async_wake_up(self, vehicle_id: ArcfoxVehicle | str) -> None:
        """Wake up the vehicle."""
        await self._send_spec_command(vehicle_id, "wake_up")

    async def _send_command(
        self,
        vehicle: ArcfoxVehicle | str,
        command: str,
        *,
        json: dict[str, Any] | None = None,
        payload_obj: ArcfoxCommandPayload | None = None,
    ) -> None:
        await self._ensure_authenticated()
        vehicle_id = self._vehicle_identifier(vehicle)
        payload = {"vehicleId": vehicle_id, "command": command}
        if json:
            payload.update(json)
        spec = self._spec_for_command(command)
        if self._command_transport is not None and (
            payload_obj is not None or spec.group is not None or spec.cmd is not None
        ):
            _LOGGER.debug(
                "ARCFOX command transport selected for %s (vehicle=%s)",
                spec.action,
                vehicle_id,
            )
            await self._command_transport.send_command(
                vehicle,
                action=spec.action,
                spec=spec,
                payload=payload_obj,
            )
            return
        raise ArcfoxTransportError(
            f"Command transport is not configured for ARCFOX action {spec.action}; "
            "configure MQTT/BCTP instead of using the placeholder HTTP fallback"
        )

    async def _send_spec_command(
        self,
        vehicle: ArcfoxVehicle | str,
        action: str,
        *builder_args: Any,
        **builder_kwargs: Any,
    ) -> None:
        spec = COMMAND_SPECS[action]
        payload = None
        if spec.builder is not None:
            payload = spec.build_payload(*builder_args, **builder_kwargs)
        await self._send_command(
            vehicle,
            spec.command,
            json=payload.to_dict() if payload is not None else None,
            payload_obj=payload,
        )

    async def _ensure_authenticated(self) -> None:
        if self._access_token:
            return
        await self.async_authenticate()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        if self._access_token:
            headers.update(self._auth_headers())
        try:
            _LOGGER.debug("ARCFOX API request: %s %s", method.upper(), path)
            self._last_request_path = path
            data = await self._transport.request_json(
                method,
                path,
                headers=headers,
                **kwargs,
            )
            self._last_success_path = path
            self._last_error = None
        except ArcfoxTransportAuthError as err:
            self._last_error = str(err)
            if self._refresh_token and not path.startswith("/auth/"):
                _LOGGER.info(
                    "ARCFOX API auth failure on %s %s, refreshing token and retrying once",
                    method.upper(),
                    path,
                )
                await self.async_refresh_access_token()
                return await self._request(method, path, **kwargs)
            _LOGGER.warning("ARCFOX API auth failure on %s %s: %s", method.upper(), path, err)
            raise ArcfoxAuthError(str(err)) from err
        except ArcfoxTransportError as err:
            self._last_error = str(err)
            _LOGGER.warning("ARCFOX API failure on %s %s: %s", method.upper(), path, err)
            raise ArcfoxApiError(str(err)) from err

        code = data.get("code")
        success = data.get("success")
        message = data.get("message") or data.get("msg") or "unknown error"

        if success is False:
            _LOGGER.warning("ARCFOX API rejected %s %s: %s", method.upper(), path, message)
            raise ArcfoxApiError(f"ARCFOX API rejected request: {message}")
        if isinstance(code, int) and code not in {0, 200}:
            _LOGGER.warning(
                "ARCFOX API returned code %s for %s %s: %s",
                code,
                method.upper(),
                path,
                message,
            )
            raise ArcfoxApiError(f"ARCFOX API returned code {code}: {message}")

        return data

    def _auth_headers(self) -> dict[str, str]:
        """Build a compatibility set of auth headers.

        The mobile app traces suggest token handling is not fully consistent
        across ARCFOX endpoints, so we send a conservative header set.
        """
        if not self._access_token:
            return {}
        token = self._access_token
        return {
            "Authorization": f"Bearer {token}",
            "accessToken": token,
            "token": token,
            "X-Access-Token": token,
        }

    @staticmethod
    def _extract_items(data: dict[str, Any]) -> list[Any]:
        candidates = (
            data.get("data"),
            data.get("vehicles"),
            data.get("list"),
            data.get("vehicle"),
        )
        for candidate in candidates:
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict):
                for key in ("vehicles", "list", "items", "records"):
                    if isinstance(candidate.get(key), list):
                        return candidate[key]
                if any(candidate.get(key) is not None for key in ("vehicleId", "vehicle_id", "id", "vin", "VIN")):
                    return [candidate]
        return []

    @staticmethod
    def _extract_vehicle_candidate(data: dict[str, Any]) -> dict[str, Any] | None:
        candidates = (
            data,
            data.get("data") if isinstance(data.get("data"), dict) else None,
        )
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if any(candidate.get(key) is not None for key in ("vehicleId", "vehicle_id", "id", "vin", "VIN")):
                return candidate
        return None

    @staticmethod
    def _vehicle_identifier(vehicle: ArcfoxVehicle | str) -> str:
        if isinstance(vehicle, ArcfoxVehicle):
            return vehicle.vehicle_id
        return str(vehicle)

    def _store_auth_data(self, data: dict[str, Any]) -> None:
        """Persist login response fields."""
        self._auth_data = data
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        if not isinstance(payload, dict):
            payload = data

        token = (
            payload.get("access_token")
            or payload.get("token")
            or payload.get("accessToken")
            or data.get("access_token")
            or data.get("token")
            or data.get("accessToken")
            or self._access_token
        )
        if not token:
            raise ArcfoxAuthError("Missing access token in ARCFOX login response")

        self._access_token = str(token)
        self._refresh_token = str(
            payload.get("refresh_token")
            or payload.get("refreshToken")
            or data.get("refresh_token")
            or data.get("refreshToken")
            or self._refresh_token
            or ""
        )
        if not self._refresh_token:
            self._refresh_token = None

        account_id = (
            payload.get("accountId")
            or payload.get("userId")
            or data.get("accountId")
            or data.get("userId")
            or self._user_id
            or self._vin
        )
        self._account_id = str(account_id)
        if self._auth_state_callback is not None:
            try:
                self._auth_state_callback(
                    {
                        "account_id": self._account_id,
                        "user_id": self._user_id,
                        "vin": self._vin,
                        "access_token": self._access_token,
                        "refresh_token": self._refresh_token,
                    }
                )
            except Exception:
                _LOGGER.exception("ARCFOX auth state callback failed")

    @staticmethod
    def _spec_for_command(command: str):
        for spec in COMMAND_SPECS.values():
            if spec.command == command:
                return spec
        raise ArcfoxApiError(f"Unknown command spec for {command}")
