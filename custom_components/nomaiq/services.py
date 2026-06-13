"""Services for the nomaiq integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_OEM_MODEL, DOMAIN, SERVICE_UNADOPT_DEVICE

_LOGGER = logging.getLogger(__name__)

UNADOPT_SCHEMA = vol.Schema({vol.Required(ATTR_OEM_MODEL): cv.string})


async def _async_unadopt(call: ServiceCall) -> None:
    """Forget a model's stored mapping; its adoption offer reappears in Repairs."""
    hass = call.hass
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError("No NomaIQ integration is currently loaded")

    model: str = call.data[ATTR_OEM_MODEL]
    deleted = False
    for entry in entries:
        manager = entry.runtime_data.adoption
        if manager is None:
            continue
        if not deleted:
            # The mapping store is global (keyed by oem_model); deleting once
            # is enough, but every loaded entry must reload to drop entities.
            await manager.store.delete_mapping(model)
            deleted = True
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
    if not deleted:
        raise ServiceValidationError("No NomaIQ mapping store available")
    _LOGGER.info("Un-adopted model %s; the adoption offer will reappear in Repairs", model)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the nomaiq services once."""
    if hass.services.has_service(DOMAIN, SERVICE_UNADOPT_DEVICE):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNADOPT_DEVICE,
        _async_unadopt,
        schema=UNADOPT_SCHEMA,
    )
