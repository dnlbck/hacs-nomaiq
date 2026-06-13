"""Platform for binary sensor integration (Noma IQ Dehumidifier alarms)."""

from __future__ import annotations

from dataclasses import dataclass

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NomaIQConfigEntry
from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity
from .factory import async_setup_mapped_platform


@dataclass(frozen=True)
class DehumBinarySensorSpec:
    """Describe a dehumidifier binary sensor."""

    property_name: str
    suffix: str
    name: str
    device_class: BinarySensorDeviceClass


DEHUM_BINARY_SENSORS: tuple[DehumBinarySensorSpec, ...] = (
    DehumBinarySensorSpec(
        property_name="water_bucket_full",
        suffix="bucket",
        name="Water bucket full",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    DehumBinarySensorSpec(
        property_name="filter_clean_alarm",
        suffix="filter",
        name="Filter clean alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Binary Sensor platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    entities: list[BinarySensorEntity] = []
    for device in coordinator.data:
        if device.oem_model_number != "dehum" or (
            manager and manager.is_forced(device.oem_model_number)
        ):
            continue
        for spec in DEHUM_BINARY_SENSORS:
            if spec.property_name in device.properties_full:
                entities.append(NomaIQDehumBinarySensor(coordinator, device, spec))

    async_add_entities(entities, update_before_add=False)
    async_setup_mapped_platform(hass, entry, async_add_entities, Platform.BINARY_SENSOR)


class NomaIQDehumBinarySensor(NomaIQEntity, BinarySensorEntity):
    """Binary sensor for a Noma IQ dehumidifier alarm property."""

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
        spec: DehumBinarySensorSpec,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device)
        self._spec = spec
        self._attr_name = f"{device.name} {spec.name}"
        self._attr_unique_id = f"nomaiq_dehum_{device.serial_number}_{spec.suffix}"
        self._attr_device_class = spec.device_class

    @property
    def is_on(self) -> bool | None:
        """Return True if the alarm is active."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value(self._spec.property_name)
        return bool(value) if value is not None else None
