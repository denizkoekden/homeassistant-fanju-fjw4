"""Thin async client for the EMaxLife / WeatherSense cloud API.

This is a faithful port of the HTTP client used by the original Homebridge
plugin. Only the three endpoints needed by the FanJu FJW4 station are
implemented:

* ``POST /account/login``             -> obtain a session token
* ``GET  /weather/getBindedDevice``   -> bound device metadata
* ``GET  /weather/devData/getRealtime`` -> realtime sensor readings
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp

from .const import API_BASE_URL, MD5_KEY

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)


class WeatherSenseError(Exception):
    """Base error for the WeatherSense cloud client."""


class WeatherSenseAuthError(WeatherSenseError):
    """Raised when authentication fails (bad credentials / token)."""


class WeatherSenseApiError(WeatherSenseError):
    """Raised when the cloud returns an unexpected response."""


class WeatherSenseApi:
    """Minimal async client for the FanJu FJW4 vendor cloud."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client.

        Args:
            session: Shared aiohttp session (use Home Assistant's).
            username: Account email used in the WeatherSense app.
            password: Account password used in the WeatherSense app.
        """
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        """Return the currently held session token, if any."""
        return self._token

    def _hash_password(self) -> str:
        """Return the MD5 hash the cloud expects for the password."""
        return hashlib.md5(
            f"{self._password}{MD5_KEY}".encode()
        ).hexdigest()

    async def login(self) -> str:
        """Authenticate and cache a session token.

        Returns:
            The session token.

        Raises:
            WeatherSenseAuthError: If the credentials are rejected.
            WeatherSenseApiError: On transport or unexpected response errors.
        """
        if not self._username or not self._password:
            raise WeatherSenseAuthError("Username and password are required")

        payload = {"email": self._username, "pwd": self._hash_password()}

        try:
            async with self._session.post(
                f"{API_BASE_URL}/account/login",
                json=payload,
                timeout=_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise WeatherSenseApiError(f"Error connecting to cloud: {err}") from err

        if not isinstance(data, dict) or data.get("status") != 0:
            message = ""
            if isinstance(data, dict):
                message = data.get("errorMsg") or data.get("message") or ""
            raise WeatherSenseAuthError(
                f"Authentication failed: {message or 'invalid credentials'}"
            )

        token = (data.get("content") or {}).get("token")
        if not token:
            raise WeatherSenseAuthError("Authentication succeeded but no token returned")

        self._token = token
        return token

    async def _authed_get(self, path: str) -> dict[str, Any]:
        """Perform an authenticated GET, re-logging in once on token failure."""
        if not self._token:
            await self.login()

        data = await self._get(path)
        if data.get("status") != 0:
            # Token may have expired - try a single fresh login and retry.
            _LOGGER.debug("Request to %s returned status %s, refreshing token", path, data.get("status"))
            await self.login()
            data = await self._get(path)

        if data.get("status") != 0:
            raise WeatherSenseApiError(
                f"Unexpected response from {path}: "
                f"{data.get('message') or data.get('errorMsg') or data}"
            )

        content = data.get("content")
        if not isinstance(content, dict):
            raise WeatherSenseApiError(f"Missing content in response from {path}")
        return content

    async def _get(self, path: str) -> dict[str, Any]:
        """Perform a raw GET with the current token header."""
        try:
            async with self._session.get(
                f"{API_BASE_URL}{path}",
                headers={"emaxToken": self._token or ""},
                timeout=_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise WeatherSenseApiError(f"Error connecting to cloud: {err}") from err

        if not isinstance(data, dict):
            raise WeatherSenseApiError(f"Malformed response from {path}")
        return data

    async def get_bound_device(self) -> dict[str, Any]:
        """Return metadata for the device bound to this account."""
        return await self._authed_get("/weather/getBindedDevice")

    async def get_realtime(self) -> dict[str, Any]:
        """Return the latest realtime state (including ``sensorDatas``)."""
        return await self._authed_get("/weather/devData/getRealtime")
