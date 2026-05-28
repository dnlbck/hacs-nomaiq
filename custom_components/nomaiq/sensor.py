"""Platform for sensor integration (Noma IQ Dehumidifier readings)."""

from __future__ import annotations

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
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
    """Set up the Noma IQ Sensor platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data

    entities: list[SensorEntity] = []
    for device in coordinator.data:
        if device.oem_model_number == "dehum" and "indoor_humidity" in device.properties_full:
            entities.append(NomaIQIndoorHumiditySensor(coordinator, device))

    async_add_entities(entities, update_before_add=False)


class NomaIQIndoorHumiditySensor(NomaIQEntity, SensorEntity):
    """Indoor humidity sensor for a Noma IQ dehumidifier."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
    ) -> None:
        """Initialize the humidity sensor."""
        super().__init__(coordinator, device)
        self._attr_name = f"{device.name} Indoor humidity"
        self._attr_unique_id = f"nomaiq_dehum_{device.serial_number}_indoor_humidity"

    @property
    def native_value(self) -> int | None:
        """Return current indoor humidity."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value("indoor_humidity")
        return int(value) if value is not None else None
