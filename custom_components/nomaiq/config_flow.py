"""Config flow for the nomaiq integration."""

from __future__ import annotations

import logging
from typing import Any

import ayla_iot_unofficial
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CLIENT_ID,
    CLIENT_SECRET,
    CONF_AI_TASK_ENTITY_ID,
    CONF_ENABLE_PROPERTY_DUMP,
    CONF_FORCE_LLM_MODELS,
    CONF_OFFER_ADOPTION,
    DEFAULT_ENABLE_PROPERTY_DUMP,
    DEFAULT_OFFER_ADOPTION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_AI_TASK_ENTITY_ID): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="ai_task")
        ),
        vol.Optional(CONF_OFFER_ADOPTION, default=DEFAULT_OFFER_ADOPTION): bool,
        vol.Optional(CONF_ENABLE_PROPERTY_DUMP, default=DEFAULT_ENABLE_PROPERTY_DUMP): bool,
        vol.Optional(CONF_FORCE_LLM_MODELS, default=""): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    hub = ayla_iot_unofficial.new_ayla_api(username, password, CLIENT_ID, CLIENT_SECRET, session)
    await hub.async_sign_in()
    return data


class NomaIQConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for nomaiq."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NomaIQOptionsFlowHandler:
        """Get the options flow for this handler."""
        return NomaIQOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        # Handle new configuration
        if user_input is not None:
            self._async_abort_entries_match({CONF_USERNAME: user_input[CONF_USERNAME]})
            try:
                await validate_input(self.hass, user_input)
            except ayla_iot_unofficial.AylaAuthError:
                errors["base"] = "invalid_auth"
            except ayla_iot_unofficial.AylaError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=DOMAIN, data=user_input)

        return self.async_show_form(step_id="user", data_schema=CONFIG_SCHEMA, errors=errors)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reauth flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except ayla_iot_unofficial.AylaAuthError:
                errors["base"] = "invalid_auth"
            except ayla_iot_unofficial.AylaError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Update the existing entry with new data
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                self.hass.config_entries.async_update_entry(entry, data=user_input)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        # Show form with current values for reauth
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return self.async_show_form(
            step_id="reauth",
            data_schema=self.add_suggested_values_to_schema(CONFIG_SCHEMA, entry.data),
            errors=errors,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
        )


class NomaIQOptionsFlowHandler(OptionsFlow):
    """Options for LLM classification of unsupported devices."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Store the entry privately (self.config_entry is deprecated)."""
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Merge over existing options: setup reads username/password from
            # options as a credentials fallback, so they must survive saves.
            merged = {**self._entry.options, **user_input}
            if not user_input.get(CONF_AI_TASK_ENTITY_ID):
                merged.pop(CONF_AI_TASK_ENTITY_ID, None)
            return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, dict(self._entry.options)
            ),
        )
