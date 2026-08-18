"""Platform for select integration (Noma IQ Dehumidifier mode/fan)."""

from __future__ import annotations

from dataclasses import dataclass, field

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.select import SelectEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NomaIQConfigEntry
from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity
from .factory import async_setup_mapped_platform


@dataclass(frozen=True)
class DehumSelectSpec:
    """Describe a dehumidifier select entity."""

    property_name: str
    suffix: str
    name: str
    options: tuple[str, ...]
    read_map: dict[str, str] = field(default_factory=dict)
    write_map: dict[str, str] = field(default_factory=dict)


DEHUM_SELECTS: tuple[DehumSelectSpec, ...] = (
    DehumSelectSpec(
        property_name="mode",
        suffix="mode",
        name="Mode",
        options=("Auto", "Continuous", "Manual"),
        read_map={"Normal": "Manual"},
        write_map={"Manual": "Normal"},
    ),
    DehumSelectSpec(
        property_name="fan_speed",
        suffix="fan_speed",
        name="Fan speed",
        options=("Low", "High"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Noma IQ Select platform."""
    coordinator: NomaIQDataUpdateCoordinator = entry.runtime_data
    manager = coordinator.adoption

    entities: list[SelectEntity] = []
    for device in coordinator.data:
        if device.oem_model_number != "dehum" or (
            manager and manager.is_forced(device.oem_model_number)
        ):
            continue
        for spec in DEHUM_SELECTS:
            if spec.property_name in device.properties_full:
                entities.append(NomaIQDehumSelect(coordinator, device, spec))

    async_add_entities(entities, update_before_add=False)
    async_setup_mapped_platform(hass, entry, async_add_entities, Platform.SELECT)


class NomaIQDehumSelect(NomaIQEntity, SelectEntity):
    """Select for a Noma IQ dehumidifier enumerated property."""

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
        spec: DehumSelectSpec,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, device)
        self._spec = spec
        self._attr_name = f"{device.name} {spec.name}"
        self._attr_unique_id = f"nomaiq_dehum_{device.serial_number}_{spec.suffix}"

    @property
    def options(self) -> list[str]:
        """Return available options, including the current value if unmapped."""
        values = list(self._spec.options)
        current = self.current_option
        if current and current not in values:
            values.append(current)
        return values

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        device = self._current_device
        if device is None:
            return None
        value = device.get_property_value(self._spec.property_name)
        if value is None:
            return None
        return self._spec.read_map.get(str(value), str(value))

    async def async_select_option(self, option: str) -> None:
        """Set the selected option."""
        await self._device.async_set_property_value(
            self._spec.property_name,
            self._spec.write_map.get(option, option),
        )
        await self.coordinator.async_request_refresh()
