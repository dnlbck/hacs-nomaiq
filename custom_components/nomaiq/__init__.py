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
from homeassistant.helpers.typing import ConfigType

from .const import CLIENT_ID, CLIENT_SECRET, DOMAIN, ISSUE_ADOPT_PREFIX, NORMAL_UPDATE_INTERVAL
from .coordinator import NomaIQDataUpdateCoordinator

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.HUMIDIFIER,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)

type NomaIQConfigEntry = ConfigEntry[NomaIQDataUpdateCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up domain-level services."""
    from .services import async_setup_services

    async_setup_services(hass)
    return True


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
    except ayla_iot_unofficial.AylaError as err:
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

    # Mapping/adoption layer. Imported here (not at module level) so a broken
    # optional layer can never take down basic setup imports.
    from .adoption import AdoptionManager
    from .mappings import load_bundled
    from .mappings.store import MappingsStore

    store = MappingsStore(hass)
    await store.async_load()
    manager = AdoptionManager(hass, entry, coordinator, store, load_bundled())
    manager.async_resolve_known()
    coordinator.adoption = manager

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    entry.async_on_unload(coordinator.async_add_listener(manager.handle_coordinator_update))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: NomaIQConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NomaIQConfigEntry) -> bool:
    """Unload a config entry."""

    await entry.runtime_data.api.async_sign_out()
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up adoption issues when the entry is removed (not on reload)."""
    from homeassistant.helpers import issue_registry as ir

    registry = ir.async_get(hass)
    prefix = f"{ISSUE_ADOPT_PREFIX}{entry.entry_id}_"
    stale = [
        issue_id
        for domain, issue_id in registry.issues
        if domain == DOMAIN and issue_id.startswith(prefix)
    ]
    for issue_id in stale:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
