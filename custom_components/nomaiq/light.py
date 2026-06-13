"""Platform for light integration."""

from __future__ import annotations

from typing import Any

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NomaIQConfigEntry
from .const import NATIVE_MODELS
from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity
from .factory import async_setup_mapped_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Light platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    for device in coordinator.data:
        # Only natively-supported models get the hand-written light; unknown
        # models with light properties go through the mapping path instead.
        if (
            device.oem_model_number in NATIVE_MODELS
            and not (manager and manager.is_forced(device.oem_model_number))
            and "light_control" in device.properties_full
        ):
            async_add_entities([NomaIQLightEntity(coordinator, device)], update_before_add=False)

    async_setup_mapped_platform(hass, entry, async_add_entities, Platform.LIGHT)


class NomaIQLightEntity(NomaIQEntity, LightEntity):
    """Representation of a NomaIQ Light."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
    ) -> None:
        """Initialize a NomaIQ light."""
        super().__init__(coordinator, device)
        light_name = device.get_property_value("light_name")
        self._attr_name = light_name or device.name
        self._attr_unique_id = f"nomaiq_light_{device.serial_number}"
        self._attr_has_entity_name = bool(light_name)

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        device = self._current_device
        return bool(device.get_property_value("light_control")) if device else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn device on."""
        await self._device.async_set_property_value("light_control", 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn device off."""
        await self._device.async_set_property_value("light_control", 0)
        await self.coordinator.async_request_refresh()
