"""Platform for sensor integration (Noma IQ Dehumidifier + Water Controller)."""

from __future__ import annotations

from dataclasses import dataclass

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, Platform
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


@dataclass(frozen=True)
class HoseSensorSpec:
    """Describe a per-unit Water Controller sensor."""

    prop_base: str  # combined with the unit as Unit{n}_{prop_base}
    suffix: str
    name: str
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None


HOSE_SENSORS: tuple[HoseSensorSpec, ...] = (
    # Battery reads as a small integer (e.g. 1), not a percentage, so it is
    # exposed raw without a battery device_class/% unit. Kept as a primary
    # (non-diagnostic) sensor since hose-unit battery level matters here.
    HoseSensorSpec(
        prop_base="Battery_Capacity",
        suffix="battery",
        name="Battery",
    ),
    HoseSensorSpec(
        prop_base="Accumulate_Usage",
        suffix="total_usage",
        name="Total water usage",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoseSensorSpec(
        prop_base="Last_Water_Usage",
        suffix="last_usage",
        name="Last water usage",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Sensor platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    entities: list[SensorEntity] = []
    for device in coordinator.data:
        forced = bool(manager and manager.is_forced(device.oem_model_number))
        if (
            device.oem_model_number == "dehum"
            and not forced
            and "indoor_humidity" in device.properties_full
        ):
            entities.append(NomaIQIndoorHumiditySensor(coordinator, device))
        if device.oem_model_number == "water-controller" and not forced:
            for unit in HOSE_CONTROLLER_UNITS:
                if not device.get_property_value(f"Unit{unit}_Pairing_Status"):
                    continue
                for spec in HOSE_SENSORS:
                    if f"Unit{unit}_{spec.prop_base}" in device.properties_full:
                        entities.append(NomaIQHoseSensor(coordinator, device, unit, spec))

    async_add_entities(entities, update_before_add=False)
    async_setup_mapped_platform(hass, entry, async_add_entities, Platform.SENSOR)


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


class NomaIQHoseSensor(NomaIQEntity, SensorEntity):
    """A read-only reading (battery, water usage) for one paired hose unit."""

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
        unit: int,
        spec: HoseSensorSpec,
    ) -> None:
        """Initialize a per-unit Water Controller sensor."""
        super().__init__(coordinator, device)
        self._unit = unit
        self._spec = spec
        self._prop = f"Unit{unit}_{spec.prop_base}"
        self._attr_name = f"{_hose_unit_name(device, unit)} {spec.name}"
        self._attr_unique_id = f"nomaiq_hose_{device.serial_number}_unit{unit}_{spec.suffix}"
        self._attr_state_class = spec.state_class
        if spec.entity_category is not None:
            self._attr_entity_category = spec.entity_category

    @property
    def native_value(self) -> int | None:
        """Return the current reading."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value(self._prop)
        return int(value) if value is not None else None
