"""Transport abstraction for ARCFOX requests."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
import logging
from datetime import datetime
import ssl
import uuid
from typing import Any
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientResponseError, ClientSession

from .bctp import BctpPublishRequest, _st_string, build_publish_request
from .models import ArcfoxVehicle
from .protocol import ArcfoxCommandPayload, ArcfoxCommandSpec
from .appserver import ArcfoxAppServerClient, ArcfoxAppServerError

_LOGGER = logging.getLogger(__name__)

class ArcfoxTransportError(Exception):
    """Base transport error."""


class ArcfoxTransportAuthError(ArcfoxTransportError):
    """Transport authentication error."""


class ArcfoxTransport(ABC):
    """Abstract transport contract for ARCFOX backends."""

    @abstractmethod
    async def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Perform a request and return a JSON object."""

    async def post_command(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Post a command payload."""
        return await self.request_json("post", path, headers=headers, json=payload or {})


class ArcfoxCommandTransport(ABC):
    """Abstract transport for remote-control command delivery."""

    @abstractmethod
    async def send_command(
        self,
        vehicle: ArcfoxVehicle | str,
        *,
        action: str,
        spec: ArcfoxCommandSpec,
        payload: ArcfoxCommandPayload | None,
        seq: int = 1,
        st: str = "",
        business_code: str | None = None,
        cyber: dict[str, Any] | None = None,
    ) -> Any:
        """Send a remote-control command."""


class ArcfoxHttpTransport(ArcfoxTransport):
    """HTTP transport used by the current placeholder API implementation."""

    def __init__(self, session: ClientSession, base_urls: Iterable[str], timeout: int) -> None:
        self._session = session
        self._base_urls = self._normalize_base_urls(base_urls)
        self._timeout = timeout
        self._ssl_context = self._build_bjev_ssl_context()

    @staticmethod
    def _normalize_base_urls(base_urls: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for base_url in base_urls:
            candidate = base_url.strip().rstrip("/")
            if not candidate or candidate in normalized:
                continue
            normalized.append(candidate)
        return normalized

    @staticmethod
    def _join_base_url(base_url: str, path: str) -> str:
        return f"{base_url}{path}"

    @staticmethod
    def _build_bjev_ssl_context() -> ssl.SSLContext | None:
        cert_dir = Path(__file__).with_name("certs")
        ca_path = cert_dir / "baic_root_ca.pem"
        client_cert_path = cert_dir / "baic_https_client.pem"
        client_key_path = cert_dir / "baic_https_client_key.pem"
        if not ca_path.exists():
            return None
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(ca_path))
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        if client_cert_path.exists() and client_key_path.exists():
            context.load_cert_chain(
                certfile=str(client_cert_path),
                keyfile=str(client_key_path),
            )
        return context

    def _ssl_for_url(self, url: str) -> ssl.SSLContext | None:
        host = urlsplit(url).hostname or ""
        if host.endswith(".bjev.com.cn"):
            return self._ssl_context
        return None

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # These headers are added by the official app's Retrofit interceptor
        # for every request.  In particular, the B2C vehicle APIs are stricter
        # than the legacy SDK endpoints and may reject otherwise valid tokens
        # when the request fingerprint is incomplete.
        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "X-Nonce": str(uuid.uuid4()),
            "X-Client-Version": "3.4.28",
        }
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        auth_error: ArcfoxTransportAuthError | None = None

        for base_url in self._base_urls:
            url = self._join_base_url(base_url, path)
            _LOGGER.debug("ARCFOX HTTP request: %s %s", method.upper(), url)
            try:
                async with asyncio.timeout(self._timeout):
                    response = await self._session.request(
                        method,
                        url,
                        headers=request_headers,
                        ssl=self._ssl_for_url(url),
                        **kwargs,
                    )
                    response.raise_for_status()
                    data = await response.json(content_type=None)
            except ClientResponseError as err:
                _LOGGER.warning(
                    "ARCFOX HTTP response error for %s %s: status=%s",
                    method.upper(),
                    url,
                    err.status,
                )
                if err.status in {401, 403}:
                    auth_error = ArcfoxTransportAuthError(f"Authentication failed: {err.status}")
                    last_error = auth_error
                    continue
                last_error = ArcfoxTransportError(f"ARCFOX HTTP error: {err.status}")
                continue
            except (ClientError, TimeoutError, ValueError) as err:
                _LOGGER.exception("ARCFOX HTTP request failed for %s %s", method.upper(), url)
                last_error = ArcfoxTransportError(f"ARCFOX request failed: {err}")
                continue

            if isinstance(data, list):
                # The B2C vehicle endpoint returns a bare array, while the
                # legacy SDK consistently wraps results in an object.
                return {"data": data}
            if not isinstance(data, dict):
                # Several Retrofit methods, including security-code/check,
                # are declared as Call<String> and return a JSON string.
                return {"data": data}
            return data

        if auth_error is not None:
            raise auth_error
        if last_error is not None:
            raise last_error
        raise ArcfoxTransportError("ARCFOX API did not return a usable response")


class ArcfoxBctpTransport(ArcfoxCommandTransport):
    """BCTP transport scaffold for future MQTT publishing."""

    def __init__(
        self,
        publisher: Callable[[str, dict[str, Any] | bytes], Awaitable[None]],
        *,
        token_getter: Callable[[], str],
        topic_channel: str = "bctp",
        topic_product: str = "N5",
        topic_scope: str = "standard",
        topic_target: str = "terminal",
        topic_suffix: str = "topic/21",
    ) -> None:
        self._publisher = publisher
        self._token_getter = token_getter
        self._topic_channel = topic_channel
        self._topic_product = topic_product
        self._topic_scope = topic_scope
        self._topic_target = topic_target
        self._topic_suffix = topic_suffix

    async def send_command(
        self,
        vehicle: ArcfoxVehicle | str,
        *,
        action: str,
        spec: ArcfoxCommandSpec,
        payload: ArcfoxCommandPayload | None,
        seq: int = 1,
        st: str = "",
        business_code: str | None = None,
        cyber: dict[str, Any] | None = None,
    ) -> BctpPublishRequest:
        """Build and publish a BCTP command envelope."""
        token = self._token_getter()
        if not token:
            raise ArcfoxTransportError("Missing access token for BCTP command transport")
        if not st:
            st = _st_string(datetime.now())
        request = build_publish_request(
            vehicle,
            action=action,
            spec=spec,
            payload=payload,
            token=token,
            seq=seq,
            st=st,
            business_code=business_code,
            cyber=cyber,
            topic_channel=self._topic_channel,
            topic_product=self._topic_product,
            topic_scope=self._topic_scope,
            topic_target=self._topic_target,
            topic_suffix=self._topic_suffix,
        )
        _LOGGER.debug("ARCFOX BCTP publish request: %s", request.to_dict())
        await self._publisher(request.topic, request.payload_bytes())
        return request


class ArcfoxAppServerCommandTransport(ArcfoxCommandTransport):
    """Deliver control commands through the AppServer TCP control channel.

    The AppServer channel (port 60115) is what the official app uses for its
    control page. It authenticates with the App token rather than the short
    lived REST ``rcToken``, so no per-command security-code exchange is needed.
    """

    def __init__(
        self,
        *,
        vin: str,
        app_token: str,
        aid: str,
        imei: str,
        host: str,
        port: int,
        timeout: int,
    ) -> None:
        self._vin = vin
        self._app_token = app_token
        self._aid = aid
        self._imei = imei
        self._host = host
        self._port = port
        self._timeout = timeout

    async def send_command(
        self,
        vehicle: ArcfoxVehicle | str,
        *,
        action: str,
        spec: ArcfoxCommandSpec,
        payload: ArcfoxCommandPayload | None,
        seq: int = 1,
        st: str = "",
        business_code: str | None = None,
        cyber: dict[str, Any] | None = None,
    ) -> Any:
        temperature: float | None = None
        if action == "set_climate_temperature" and payload is not None and payload.p1 is not None:
            temperature = float(payload.p1)

        def _sync_send() -> dict[str, Any]:
            client = ArcfoxAppServerClient(
                vin=self._vin,
                app_token=self._app_token,
                aid=self._aid,
                imei=self._imei,
                host=self._host,
                port=self._port,
                timeout=self._timeout,
            )
            try:
                client.connect()
                result = client.send_action(action, temperature=temperature)
                if result.get("error"):
                    raise ArcfoxTransportError(
                        f"AppServer control {action} failed: {result['error']}"
                    )
                return result
            except ArcfoxAppServerError as err:
                raise ArcfoxTransportError(f"AppServer control {action} failed: {err}") from err
            finally:
                client.close()

        _LOGGER.debug("ARCFOX AppServer command: action=%s vin=%s", action, self._vin)
        return await asyncio.to_thread(_sync_send)
