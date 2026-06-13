"""Platform for switch integration (Noma IQ Water/Hose Controller)."""

from __future__ import annotations

from typing import Any

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NomaIQConfigEntry
from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity
from .factory import async_setup_mapped_platform

HOSE_CONTROLLER_UNITS = (1, 2, 3, 4)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Switch platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    entities: list[SwitchEntity] = []
    for device in coordinator.data:
        if device.oem_model_number == "water-controller" and not (
            manager and manager.is_forced(device.oem_model_number)
        ):
            for unit in HOSE_CONTROLLER_UNITS:
                if device.get_property_value(f"Unit{unit}_Pairing_Status"):
                    entities.append(NomaIQHoseControlSwitch(coordinator, device, unit))

    async_add_entities(entities, update_before_add=False)
    async_setup_mapped_platform(hass, entry, async_add_entities, Platform.SWITCH)


class NomaIQHoseControlSwitch(NomaIQEntity, SwitchEntity):
    """One paired hose/zone on a Noma IQ Water Controller."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
        unit: int,
    ) -> None:
        """Initialize a hose-control switch for one unit."""
        super().__init__(coordinator, device)
        self._unit = unit
        self._switch_prop = f"Unit{unit}_Manual_Switch"
        self._status_prop = f"Unit{unit}_Manual_SwitchStatus"

        unit_name = device.get_property_value(f"Unit{unit}_Device_Name")
        self._attr_name = unit_name or f"{device.name} Unit {unit}"
        self._attr_unique_id = f"nomaiq_hose_{device.serial_number}_unit{unit}"

    @property
    def is_on(self) -> bool | None:
        """Return True if the unit is currently running."""
        device = self._current_device
        if device is None:
            return None
        return bool(device.get_property_value(self._status_prop))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the hose unit (runs for its configured Manual_Duration)."""
        await self._device.async_set_property_value(self._switch_prop, 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the hose unit."""
        await self._device.async_set_property_value(self._switch_prop, 0)
        await self.coordinator.async_request_refresh()
