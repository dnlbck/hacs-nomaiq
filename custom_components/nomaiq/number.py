"""Platform for number integration (Noma IQ Dehumidifier setpoints)."""

from __future__ import annotations

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, Platform, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NomaIQConfigEntry
from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity
from .factory import async_setup_mapped_platform

HOSE_CONTROLLER_UNITS = (1, 2, 3, 4)


def _hose_unit_name(device: ayla_iot_unofficial.device.Device, unit: int) -> str:
    """Return the controller-configured name for a hose unit, with a fallback."""
    name = device.get_property_value(f"Unit{unit}_Device_Name")
    return name or f"{device.name} Unit {unit}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Number platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    entities: list[NumberEntity] = []
    for device in coordinator.data:
        forced = bool(manager and manager.is_forced(device.oem_model_number))
        if (
            device.oem_model_number == "dehum"
            and not forced
            and "humidity" in device.properties_full
        ):
            entities.append(NomaIQTargetHumidityNumber(coordinator, device))
        if device.oem_model_number == "water-controller" and not forced:
            for unit in HOSE_CONTROLLER_UNITS:
                if device.get_property_value(f"Unit{unit}_Pairing_Status"):
                    entities.append(NomaIQHoseDurationNumber(coordinator, device, unit))

    async_add_entities(entities, update_before_add=False)
    async_setup_mapped_platform(hass, entry, async_add_entities, Platform.NUMBER)


class NomaIQTargetHumidityNumber(NomaIQEntity, NumberEntity):
    """Target humidity slider for a Noma IQ dehumidifier."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 35
    _attr_native_max_value = 85
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
    ) -> None:
        """Initialize the target humidity number."""
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Target humidity"
        self._attr_unique_id = f"nomaiq_dehum_{device.serial_number}_target_humidity"

    @property
    def native_value(self) -> float | None:
        """Return the current target humidity."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value("humidity")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the target humidity."""
        await self._device.async_set_property_value("humidity", int(value))
        await self.coordinator.async_request_refresh()


class NomaIQHoseDurationNumber(NomaIQEntity, NumberEntity):
    """Manual run duration for one paired hose unit on a Water Controller.

    This is how long the unit waters when its switch is turned on
    (Unit{n}_Manual_Switch); the controller counts down Manual_Duration.
    """

    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
        unit: int,
    ) -> None:
        """Initialize the manual-duration number for one hose unit."""
        super().__init__(coordinator, device)
        self._unit = unit
        self._prop = f"Unit{unit}_Manual_Duration"
        self._attr_name = f"{_hose_unit_name(device, unit)} Manual duration"
        self._attr_unique_id = f"nomaiq_hose_{device.serial_number}_unit{unit}_manual_duration"

    @property
    def native_value(self) -> float | None:
        """Return the configured manual run duration."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value(self._prop)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the manual run duration."""
        await self._device.async_set_property_value(self._prop, int(value))
        await self.coordinator.async_request_refresh()
