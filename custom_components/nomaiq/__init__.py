"""The nomaiq integration."""

from __future__ import annotations

import logging
from datetime import timedelta

import ayla_iot_unofficial
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CLIENT_ID, CLIENT_SECRET, NORMAL_UPDATE_INTERVAL
from .coordinator import NomaIQDataUpdateCoordinator

_PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.COVER, Platform.SWITCH]
_LOGGER = logging.getLogger(__name__)

type NomaIQConfigEntry = ConfigEntry[NomaIQDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: NomaIQConfigEntry) -> bool:
    """Set up nomaiq from a config entry."""

    config = entry.data
    options = entry.options

    username = options.get(CONF_USERNAME, config.get(CONF_USERNAME, ""))
    password = options.get(CONF_PASSWORD, config.get(CONF_PASSWORD, ""))

    session = async_get_clientsession(hass)
    api = ayla_iot_unofficial.new_ayla_api(username, password, CLIENT_ID, CLIENT_SECRET, session)

    try:
        await api.async_sign_in()
    except ayla_iot_unofficial.AylaAuthError as err:
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except ayla_iot_unofficial.AylaApiError as err:
        raise ConfigEntryNotReady(f"API error: {err}") from err
    except Exception as err:
        _LOGGER.exception("Unexpected error during setup", extra={"error": err})
        raise ConfigEntryNotReady(f"Unexpected error: {err}") from err

    coordinator = NomaIQDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        update_interval=timedelta(seconds=NORMAL_UPDATE_INTERVAL),
        api=api,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NomaIQConfigEntry) -> bool:
    """Unload a config entry."""

    await entry.runtime_data.api.async_sign_out()
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
