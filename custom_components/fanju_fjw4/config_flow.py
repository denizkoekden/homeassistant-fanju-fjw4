"""Config flow for the FanJu FJW4 weather station integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import WeatherSenseApi, WeatherSenseAuthError, WeatherSenseError
from .const import (
    CLOUD_UPLOAD_HOST,
    CLOUD_UPLOAD_PORT,
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
    MANUFACTURER,
    MIN_SCAN_INTERVAL,
    MODE_CLOUD,
    MODE_LOCAL,
    MODEL,
)
from .coordinator import FanjuConfigEntry
from .hiflying import (
    HiflyingConfigureResult,
    HiflyingError,
    HiflyingStation,
    discover_station,
    discover_stations,
    ensure_upload_target,
    local_source_ip_for,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


def _scan_interval_selector() -> NumberSelector:
    """Return a number selector for the polling interval (seconds)."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_SCAN_INTERVAL,
            max=86400,
            step=1,
            unit_of_measurement="s",
            mode=NumberSelectorMode.BOX,
        )
    )


async def _validate_credentials(
    hass: Any, username: str, password: str
) -> dict[str, Any]:
    """Validate credentials and return the bound device metadata.

    Raises:
        WeatherSenseAuthError: If the credentials are rejected.
        WeatherSenseError: On connection or unexpected response errors.
    """
    # verify_ssl=False: the vendor cloud serves an expired certificate.
    api = WeatherSenseApi(
        async_get_clientsession(hass, verify_ssl=False), username, password
    )
    await api.login()
    return await api.get_bound_device()


async def _discover_local_station(hass: Any) -> HiflyingStation | None:
    """Return the first discovered Hi-Flying station, if any."""
    stations = await hass.async_add_executor_job(discover_stations)
    return stations[0] if stations else None


async def _infer_target_host(hass: Any, station_host: str) -> str:
    """Return the Home Assistant host IP reachable by the station."""
    return await hass.async_add_executor_job(local_source_ip_for, station_host)


async def _configure_local_station(
    hass: Any, station_host: str, target_host: str, listen_port: int
) -> tuple[HiflyingStation | None, HiflyingConfigureResult]:
    """Point the station at Home Assistant and return read-back metadata."""
    station = await hass.async_add_executor_job(discover_station, station_host)
    result = await hass.async_add_executor_job(
        ensure_upload_target, station_host, target_host, listen_port
    )
    return station, result


def _cloud_forward_target(
    result: HiflyingConfigureResult, target_host: str, listen_port: int
) -> tuple[str, int]:
    """Return the best cloud target for hybrid forwarding."""
    before = result.before
    if before.host.lower() != target_host.lower() or before.port != listen_port:
        return before.host, before.port
    return CLOUD_UPLOAD_HOST, CLOUD_UPLOAD_PORT


class FanjuConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for FanJu FJW4."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize discovery state for the flow."""
        super().__init__()
        self._discovered_station: HiflyingStation | None = None
        self._local_target_host: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose between cloud polling and local UDP push."""
        return self.async_show_menu(
            step_id="user", menu_options=[MODE_CLOUD, MODE_LOCAL]
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle cloud setup where the user enters WeatherSense credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            try:
                device = await _validate_credentials(self.hass, username, password)
            except WeatherSenseAuthError:
                errors["base"] = "invalid_auth"
            except WeatherSenseError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating FanJu FJW4 credentials")
                errors["base"] = "unknown"
            else:
                unique_id = str(device.get("sn") or device.get("mac") or username)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = device.get("alias") or f"{MANUFACTURER} {MODEL}"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_MODE: MODE_CLOUD,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                    options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
                )

        return self.async_show_form(
            step_id="cloud",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle local setup and optional automatic station configuration."""
        errors: dict[str, str] = {}

        if self._discovered_station is None:
            try:
                self._discovered_station = await _discover_local_station(self.hass)
            except OSError:
                _LOGGER.debug("No FanJu/Hi-Flying station discovered", exc_info=True)

        default_station_host = (
            self._discovered_station.ip if self._discovered_station else ""
        )
        if default_station_host and self._local_target_host is None:
            try:
                self._local_target_host = await _infer_target_host(
                    self.hass, default_station_host
                )
            except OSError:
                _LOGGER.debug(
                    "Could not infer Home Assistant source IP for %s",
                    default_station_host,
                    exc_info=True,
                )

        if user_input is not None:
            port = int(user_input[CONF_LISTEN_PORT])
            forward = bool(user_input[CONF_FORWARD])
            configure_station = bool(user_input[CONF_CONFIGURE_STATION])
            station_host = str(user_input.get(CONF_STATION_HOST) or "").strip()
            target_host = str(user_input.get(CONF_TARGET_HOST) or "").strip()
            station_mac = (
                self._discovered_station.mac if self._discovered_station else None
            )
            cloud_host = CLOUD_UPLOAD_HOST
            cloud_port = CLOUD_UPLOAD_PORT

            if configure_station:
                if not station_host:
                    errors["base"] = "station_not_found"
                else:
                    try:
                        if not target_host:
                            target_host = await _infer_target_host(
                                self.hass, station_host
                            )
                        station, result = await _configure_local_station(
                            self.hass, station_host, target_host, port
                        )
                    except (HiflyingError, OSError):
                        _LOGGER.exception(
                            "Failed to configure FanJu station %s", station_host
                        )
                        errors["base"] = "cannot_configure_station"
                    else:
                        if station is not None:
                            station_mac = station.mac
                        cloud_host, cloud_port = _cloud_forward_target(
                            result, target_host, port
                        )

            if not errors:
                unique_id = station_mac or f"{DOMAIN}_local_{station_host or port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                data: dict[str, Any] = {
                    CONF_MODE: MODE_LOCAL,
                    CONF_LISTEN_PORT: port,
                    CONF_CONFIGURE_STATION: configure_station,
                    CONF_CLOUD_UPLOAD_HOST: cloud_host,
                    CONF_CLOUD_UPLOAD_PORT: cloud_port,
                }
                if station_host:
                    data[CONF_STATION_HOST] = station_host
                if station_mac:
                    data[CONF_STATION_MAC] = station_mac
                if target_host:
                    data[CONF_TARGET_HOST] = target_host
                return self.async_create_entry(
                    title=f"{MANUFACTURER} {MODEL} (local)",
                    data=data,
                    options={CONF_FORWARD: forward},
                )

        if user_input is not None:
            default_station_host = str(
                user_input.get(CONF_STATION_HOST) or default_station_host
            )
            self._local_target_host = str(
                user_input.get(CONF_TARGET_HOST) or self._local_target_host or ""
            )

        discovered = (
            f"{self._discovered_station.ip} / {self._discovered_station.mac}"
            if self._discovered_station
            else "-"
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LISTEN_PORT, default=DEFAULT_LISTEN_PORT
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=65535, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_FORWARD, default=True): BooleanSelector(),
                vol.Required(
                    CONF_CONFIGURE_STATION, default=bool(default_station_host)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_STATION_HOST, default=default_station_host
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_TARGET_HOST, default=self._local_target_host or ""
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            }
        )
        return self.async_show_form(
            step_id="local",
            data_schema=schema,
            errors=errors,
            description_placeholders={"discovered": discovered},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication after credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication with fresh credentials."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            try:
                device = await _validate_credentials(self.hass, username, password)
            except WeatherSenseAuthError:
                errors["base"] = "invalid_auth"
            except WeatherSenseError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during FanJu FJW4 reauth")
                errors["base"] = "unknown"
            else:
                unique_id = str(device.get("sn") or device.get("mac") or username)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={CONF_USERNAME: reauth_entry.data[CONF_USERNAME]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: FanjuConfigEntry) -> FanjuOptionsFlow:
        """Return the options flow handler."""
        return FanjuOptionsFlow()


class FanjuOptionsFlow(OptionsFlow):
    """Handle options (polling interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options: polling interval (cloud) or hybrid forward (local)."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        if self.config_entry.data.get(CONF_MODE) == MODE_LOCAL:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_FORWARD,
                        default=self.config_entry.options.get(CONF_FORWARD, True),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_CONFIGURE_STATION,
                        default=self.config_entry.options.get(
                            CONF_CONFIGURE_STATION,
                            self.config_entry.data.get(CONF_CONFIGURE_STATION, False),
                        ),
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_STATION_HOST,
                        default=self.config_entry.options.get(
                            CONF_STATION_HOST,
                            self.config_entry.data.get(CONF_STATION_HOST, ""),
                        ),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(
                        CONF_TARGET_HOST,
                        default=self.config_entry.options.get(
                            CONF_TARGET_HOST,
                            self.config_entry.data.get(CONF_TARGET_HOST, ""),
                        ),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                }
            )
        else:
            current = self.config_entry.options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            )
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current
                    ): _scan_interval_selector()
                }
            )
        return self.async_show_form(step_id="init", data_schema=schema)
