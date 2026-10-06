"""Config flow for the ENTSO-E integration."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import EntsoeApiClient, EntsoeAuthError, EntsoeError
from .const import AREA_CODES, CONF_API_KEY, CONF_AREA, CONF_VAT, DEFAULT_VAT, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_AREA): vol.In(list(AREA_CODES)),
        vol.Optional(CONF_VAT, default=DEFAULT_VAT): vol.Coerce(float),
    }
)


async def _validate_credentials(hass, api_key: str, area_name: str) -> None:
    session = async_get_clientsession(hass)
    client = EntsoeApiClient(session, api_key)
    now = dt_util.utcnow()
    await client.async_get_prices(AREA_CODES[area_name], now - timedelta(hours=1), now)


class EntsoeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for the ENTSO-E integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_API_KEY], user_input[CONF_AREA]
                )
            except EntsoeAuthError:
                errors["base"] = "invalid_auth"
            except EntsoeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_AREA], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_API_KEY], user_input[CONF_AREA]
                )
            except EntsoeAuthError:
                errors["base"] = "invalid_auth"
            except EntsoeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry, data=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_KEY, default=reconfigure_entry.data[CONF_API_KEY]
                ): str,
                vol.Required(
                    CONF_AREA, default=reconfigure_entry.data[CONF_AREA]
                ): vol.In(list(AREA_CODES)),
                vol.Optional(
                    CONF_VAT,
                    default=reconfigure_entry.data.get(CONF_VAT, DEFAULT_VAT),
                ): vol.Coerce(float),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_API_KEY], reauth_entry.data[CONF_AREA]
                )
            except EntsoeAuthError:
                errors["base"] = "invalid_auth"
            except EntsoeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "EntsoeOptionsFlow":
        return EntsoeOptionsFlow(config_entry)


class EntsoeOptionsFlow(config_entries.OptionsFlow):
    """Allow changing VAT % without re-entering the API key."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_vat = self._config_entry.options.get(
            CONF_VAT, self._config_entry.data.get(CONF_VAT, DEFAULT_VAT)
        )
        schema = vol.Schema(
            {vol.Optional(CONF_VAT, default=current_vat): vol.Coerce(float)}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
