"""Platform for humidifier integration (Noma IQ Dehumidifier)."""

from __future__ import annotations

from typing import Any

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.humidifier import HumidifierDeviceClass, HumidifierEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NomaIQConfigEntry
from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Humidifier platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    entities: list[HumidifierEntity] = []
    for device in coordinator.data:
        if (
            device.oem_model_number == "dehum"
            and not (manager and manager.is_forced(device.oem_model_number))
            and "power" in device.properties_full
        ):
            entities.append(NomaIQDehumidifierEntity(coordinator, device))

    async_add_entities(entities, update_before_add=False)


class NomaIQDehumidifierEntity(NomaIQEntity, HumidifierEntity):
    """Representation of a Noma IQ Dehumidifier."""

    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_min_humidity = 35
    _attr_max_humidity = 85

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
    ) -> None:
        """Initialize the dehumidifier."""
        super().__init__(coordinator, device)
        self._attr_name = device.name
        self._attr_unique_id = f"nomaiq_dehumidifier_{device.serial_number}"

    @property
    def is_on(self) -> bool | None:
        """Return True if the dehumidifier is on."""
        device = self._current_device
        return bool(device.get_property_value("power")) if device else None

    @property
    def current_humidity(self) -> int | None:
        """Return the current indoor humidity reading."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value("indoor_humidity")
        return int(value) if value is not None else None

    @property
    def target_humidity(self) -> int | None:
        """Return the target humidity setpoint."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value("humidity")
        return int(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the dehumidifier on."""
        await self._device.async_set_property_value("power", 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the dehumidifier off."""
        await self._device.async_set_property_value("power", 0)
        await self.coordinator.async_request_refresh()

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity."""
        await self._device.async_set_property_value("humidity", int(humidity))
        await self.coordinator.async_request_refresh()
