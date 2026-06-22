"""Data update coordinator for the FanJu FJW4 weather station.

Two modes share one coordinator:

* ``cloud`` - polls the EMaxLife cloud (``getRealtime``) on an interval.
* ``local`` - binds a UDP socket and decodes the station's own uploads as they
  arrive (push). In hybrid operation each datagram is relayed on to the vendor
  cloud and the cloud's reply is relayed back, so the WeatherSense app keeps
  working while Home Assistant reads the station locally.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import socket
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
from .const import (
    CLOUD_UPLOAD_HOST,
    CLOUD_UPLOAD_PORT,
    CONFIG_CHECK_INTERVAL,
    CONF_CLOUD_UPLOAD_HOST,
    CONF_CLOUD_UPLOAD_PORT,
    CONF_CONFIGURE_STATION,
    CONF_FORWARD,
    CONF_LISTEN_PORT,
    CONF_MODE,
    CONF_STATION_HOST,
    CONF_STATION_MAC,
    CONF_TARGET_HOST,
    DEFAULT_LISTEN_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODE_CLOUD,
    MODE_LOCAL,
)
from .hiflying import (
    HiflyingConfigureResult,
    HiflyingError,
    discover_stations,
    ensure_upload_target,
    local_source_ip_for,
)
from .protocol import parse_upload

_LOGGER = logging.getLogger(__name__)

type FanjuConfigEntry = ConfigEntry[FanjuDataUpdateCoordinator]


class _UploadProtocol(asyncio.DatagramProtocol):
    """Forwards received datagrams to the coordinator."""

    def __init__(self, coordinator: FanjuDataUpdateCoordinator) -> None:
        self._coordinator = coordinator

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._coordinator._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._coordinator._handle_datagram(data, addr)


class FanjuDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for both the cloud (poll) and local (UDP push) paths."""

    config_entry: FanjuConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FanjuConfigEntry) -> None:
        """Initialize the coordinator."""
        self.mode: str = entry.data.get(CONF_MODE, MODE_CLOUD)
        # Bound device metadata (cloud: from getBindedDevice; local: learned from
        # the first upload's embedded MAC).
        self.device: dict[str, Any] = {}

        if self.mode == MODE_LOCAL:
            super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry)
            self._listen_port: int = entry.data.get(
                CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT
            )
            self._forward: bool = entry.options.get(CONF_FORWARD, True)
            self._configure_station: bool = entry.options.get(
                CONF_CONFIGURE_STATION,
                entry.data.get(CONF_CONFIGURE_STATION, False),
            )
            self._station_host: str | None = entry.options.get(
                CONF_STATION_HOST, entry.data.get(CONF_STATION_HOST)
            )
            self._station_mac: str | None = entry.data.get(CONF_STATION_MAC)
            self._target_host: str | None = entry.options.get(
                CONF_TARGET_HOST, entry.data.get(CONF_TARGET_HOST)
            )
            self._cloud_upload_host: str = entry.data.get(
                CONF_CLOUD_UPLOAD_HOST, CLOUD_UPLOAD_HOST
            )
            self._cloud_upload_port: int = entry.data.get(
                CONF_CLOUD_UPLOAD_PORT, CLOUD_UPLOAD_PORT
            )
            self._transport: asyncio.DatagramTransport | None = None
            self._cloud_ip: str | None = None
            self._station_addr: tuple[str, int] | None = None
            self._config_task: asyncio.Task[None] | None = None
            return

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

    # -- cloud path -------------------------------------------------------- #
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

    # -- local path -------------------------------------------------------- #
    async def async_start_local(self) -> None:
        """Bind the UDP listener (and resolve the cloud IP for forwarding)."""
        if self._forward:
            try:
                self._cloud_ip = await self.hass.async_add_executor_job(
                    socket.gethostbyname, self._cloud_upload_host
                )
            except OSError as err:
                _LOGGER.warning(
                    "Could not resolve %s for forwarding: %s",
                    self._cloud_upload_host,
                    err,
                )

        await self.hass.loop.create_datagram_endpoint(
            lambda: _UploadProtocol(self),
            local_addr=("0.0.0.0", self._listen_port),
        )
        _LOGGER.info("Listening for FanJu uploads on UDP :%s", self._listen_port)

        if self._configure_station:
            await self._async_reconcile_station_config()
            self._config_task = self.hass.loop.create_task(
                self._async_station_config_monitor()
            )

    def async_stop_local(self) -> None:
        """Close the UDP listener."""
        if self._config_task is not None:
            self._config_task.cancel()
            self._config_task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def _async_station_config_monitor(self) -> None:
        """Periodically ensure the station still uploads to Home Assistant."""
        while True:
            await asyncio.sleep(CONFIG_CHECK_INTERVAL)
            await self._async_reconcile_station_config()

    async def _async_reconcile_station_config(self) -> None:
        """Check and repair the station's upload target when configured."""
        if not self._station_host:
            _LOGGER.debug("Skipping station config check: no station host configured")
            return

        try:
            host, target_host, result = await self.hass.async_add_executor_job(
                self._reconcile_station_config
            )
        except HiflyingError as err:
            _LOGGER.warning("Could not verify FanJu station upload target: %s", err)
            return
        except OSError as err:
            _LOGGER.warning("Could not reach FanJu station for config check: %s", err)
            return

        if host != self._station_host:
            self._station_host = host
            data = dict(self.config_entry.data)
            data[CONF_STATION_HOST] = host
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)

        if not self._target_host and target_host:
            self._target_host = target_host
            data = dict(self.config_entry.data)
            data[CONF_TARGET_HOST] = target_host
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)

        if result.changed:
            _LOGGER.info(
                "Updated FanJu station upload target from %s to %s",
                result.before.command_value(),
                result.after.command_value(),
            )

    def _reconcile_station_config(
        self,
    ) -> tuple[str, str, HiflyingConfigureResult]:
        """Blocking worker for checking and repairing the module configuration."""
        station_host = self._station_host
        if not station_host:
            raise HiflyingError("No station host configured")

        target_host = self._target_host or local_source_ip_for(station_host)

        try:
            result = ensure_upload_target(
                station_host, target_host, self._listen_port
            )
            return station_host, target_host, result
        except HiflyingError:
            if not self._station_mac:
                raise

        for station in discover_stations():
            if station.mac == self._station_mac:
                target_host = self._target_host or local_source_ip_for(station.ip)
                result = ensure_upload_target(
                    station.ip, target_host, self._listen_port
                )
                return station.ip, target_host, result

        raise HiflyingError(
            f"Station {self._station_mac} was not found during discovery"
        )

    def _handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle a datagram from the station or a reply from the cloud."""
        # Reply from the cloud -> relay back to the station so it gets its ack.
        if self._cloud_ip and addr[0] == self._cloud_ip:
            if self._station_addr and self._transport:
                self._transport.sendto(data, self._station_addr)
            return

        self._station_addr = addr
        parsed = parse_upload(data)
        if parsed is not None:
            if not self.device and parsed.get("mac"):
                self.device = {"mac": parsed["mac"], "sn": parsed["mac"]}
            self.async_set_updated_data(parsed)

        # Hybrid: relay the raw upload on to the vendor cloud.
        if self._forward and self._cloud_ip and self._transport:
            self._transport.sendto(data, (self._cloud_ip, self._cloud_upload_port))
