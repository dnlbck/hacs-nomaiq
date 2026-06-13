"""Platform for cover integration."""

from __future__ import annotations

import time
from typing import Any

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NomaIQConfigEntry
from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity
from .factory import async_setup_mapped_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Cover platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    for device in coordinator.data:
        if device.oem_model_number == "gdo" and not (
            manager and manager.is_forced(device.oem_model_number)
        ):
            async_add_entities(
                [NomaIQGarageDoorOpenerEntity(coordinator, device)],
                update_before_add=False,
            )

    async_setup_mapped_platform(hass, entry, async_add_entities, Platform.COVER)


class NomaIQGarageDoorOpenerEntity(NomaIQEntity, CoverEntity):
    """Representation of a NomaIQ Garage Door Opener."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
    ) -> None:
        """Initialize a NomaIQ Garage Door Opener."""
        super().__init__(coordinator, device)
        self._attr_name = device.name
        self._attr_unique_id = f"nomaiq_cover_{device.serial_number}"

    def _get_door_status(self) -> str | None:
        """Get the current door status."""
        device = self._current_device
        return device.get_property_value("door_status") if device else None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Sync transition state with the latest door_status, then notify HA."""
        door_status = self._get_door_status()
        self.coordinator.set_device_transition_state(
            self._device.serial_number,
            door_status in ("opening", "closing"),
        )
        super()._handle_coordinator_update()

    @property
    def is_closed(self) -> bool | None:
        """Return True if door is closed."""
        return self._get_door_status() == "closed"

    @property
    def is_closing(self) -> bool | None:
        """Return True if door is closing."""
        return self._get_door_status() == "closing"

    @property
    def is_opening(self) -> bool | None:
        """Return True if door is opening."""
        return self._get_door_status() == "opening"

    async def _toggle_door(self) -> None:
        """Send the toggle command and flag the device as in transition."""
        await self._device.async_set_property_value("door_toggle", str(int(time.time())))
        self.coordinator.set_device_transition_state(self._device.serial_number, True)
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the door."""
        await self._toggle_door()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the door."""
        await self._toggle_door()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the door."""
        await self._toggle_door()
