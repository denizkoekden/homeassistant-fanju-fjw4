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
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import WeatherSenseApi, WeatherSenseAuthError, WeatherSenseError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    MIN_SCAN_INTERVAL,
    MODEL,
)
from .coordinator import FanjuConfigEntry

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


class FanjuConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for FanJu FJW4."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step where the user enters credentials."""
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
                    data={CONF_USERNAME: username, CONF_PASSWORD: password},
                    options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
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
        """Manage the polling interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

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
