"""Data update coordinator for the FanJu FJW4 weather station."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WeatherSenseApi,
    WeatherSenseAuthError,
    WeatherSenseError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type FanjuConfigEntry = ConfigEntry[FanjuDataUpdateCoordinator]


class FanjuDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the WeatherSense cloud for realtime data."""

    config_entry: FanjuConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FanjuConfigEntry) -> None:
        """Initialize the coordinator."""
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=scan_interval),
        )
        # The vendor cloud (app.emaxlife.net) regularly serves an expired TLS
        # certificate, so we must skip certificate verification - the official
        # WeatherSense app does the same. verify_ssl=False returns a separate
        # shared session, so other integrations keep verifying normally.
        self.api = WeatherSenseApi(
            async_get_clientsession(hass, verify_ssl=False),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        # Bound device metadata, populated on the first refresh.
        self.device: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest realtime state from the cloud."""
        try:
            if not self.device:
                self.device = await self.api.get_bound_device()
            return await self.api.get_realtime()
        except WeatherSenseAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WeatherSenseError as err:
            raise UpdateFailed(str(err)) from err
