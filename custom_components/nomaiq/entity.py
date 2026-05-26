"""Base entity for the nomaiq integration."""

from __future__ import annotations

import ayla_iot_unofficial.device
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NomaIQDataUpdateCoordinator


class NomaIQEntity(CoordinatorEntity[NomaIQDataUpdateCoordinator]):
    """Base class for all NomaIQ entities."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
    ) -> None:
        """Initialize the entity bound to a NomaIQ device."""
        super().__init__(coordinator)
        self._device = device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.serial_number)},
            name=device.name,
            manufacturer="Noma IQ",
            model=device.oem_model_number,
        )

    @property
    def _current_device(self) -> ayla_iot_unofficial.device.Device | None:
        """Return the latest device snapshot from the coordinator."""
        return next(
            (d for d in self.coordinator.data if d.serial_number == self._device.serial_number),
            None,
        )

    @property
    def available(self) -> bool:
        """Return True only if the coordinator and device are both healthy."""
        return super().available and self._current_device is not None
