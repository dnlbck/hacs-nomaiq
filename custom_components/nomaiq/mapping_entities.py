"""Mapping-driven entity classes.

Each class renders one EntityMapping spec (from an LLM-generated, bundled, or
user-stored mapping) against a live Ayla device. All six classes live in this
module so the factory can map kind -> class without circular imports.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

import ayla_iot_unofficial
import ayla_iot_unofficial.device
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory

from .coordinator import NomaIQDataUpdateCoordinator
from .entity import NomaIQEntity
from .mappings.schema import EntityMapping


class _SafeDict(dict):
    """Leave unknown placeholders intact instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_template(template: str | None, ctx: dict[str, Any]) -> str | None:
    """Format a mapping template; LLM-produced stray placeholders never raise."""
    if not template:
        return None
    try:
        return template.format_map(_SafeDict(ctx))
    except Exception:
        return template


def _norm(value: Any) -> Any:
    """Normalize for comparison/writes: numeric strings become ints."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    return value


_ENTITY_CATEGORIES = {
    "diagnostic": EntityCategory.DIAGNOSTIC,
    "config": EntityCategory.CONFIG,
}


class MappingEntityBase(NomaIQEntity):
    """Base for entities driven by an EntityMapping spec."""

    def __init__(
        self,
        coordinator: NomaIQDataUpdateCoordinator,
        device: ayla_iot_unofficial.device.Device,
        spec: EntityMapping,
        ctx: dict[str, Any] | None = None,
    ) -> None:
        """Resolve the spec's templates against this device (and fanout unit)."""
        super().__init__(coordinator, device)
        self._spec = spec
        ctx = {"device_name": device.name, **(ctx or {})}
        self._state_prop = format_template(spec.state_property, ctx)
        self._command_prop = format_template(spec.command_property, ctx)

        suffix = format_template(spec.id_suffix, ctx) or self._state_prop or spec.kind
        self._attr_unique_id = f"{device.serial_number}_{spec.kind}_{suffix}"

        name = None
        name_prop = format_template(spec.name_property, ctx)
        if name_prop:
            name = device.get_property_value(name_prop) or None
        if not name:
            name = format_template(spec.name_fallback, ctx)
        self._attr_name = name or f"{device.name} {suffix}"

        if spec.entity_category in _ENTITY_CATEGORIES:
            self._attr_entity_category = _ENTITY_CATEGORIES[spec.entity_category]

    def _raw_value(self) -> Any:
        """Return the current value of the state property, or None if offline.

        Note: the Ayla library returns False (not None) for missing properties.
        """
        device = self._current_device
        if device is None or self._state_prop is None:
            return None
        return device.get_property_value(self._state_prop)

    def _matches(self, value: Any, target: Any) -> bool:
        return _norm(value) == _norm(target)

    async def _async_write(self, value: Any, *, refresh: bool = True) -> None:
        """Write a value to the command property and refresh."""
        if self._command_prop is None:
            raise HomeAssistantError(f"{self.entity_id} has no command property")
        try:
            await self._device.async_set_property_value(self._command_prop, value)
        except ayla_iot_unofficial.AylaError as err:
            raise HomeAssistantError(
                f"Failed to set {self._command_prop} on {self._device.name}: {err}"
            ) from err
        if refresh:
            await self.coordinator.async_request_refresh()


class MappingSensor(MappingEntityBase, SensorEntity):
    """Read-only sensor for a mapped property."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        spec = self._spec
        if spec.device_class:
            with contextlib.suppress(ValueError):
                self._attr_device_class = SensorDeviceClass(spec.device_class)
        if spec.unit_of_measurement:
            self._attr_native_unit_of_measurement = spec.unit_of_measurement

    @property
    def native_value(self) -> Any:
        value = self._raw_value()
        if value is None:
            return None
        # HA state values must be primitives; stringify anything exotic.
        if isinstance(value, (bool, int, float, str)):
            return value
        return str(value)


class MappingBinarySensor(MappingEntityBase, BinarySensorEntity):
    """Binary sensor for a mapped property."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        spec = self._spec
        if spec.device_class:
            with contextlib.suppress(ValueError):
                self._attr_device_class = BinarySensorDeviceClass(spec.device_class)

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value()
        if value is None:
            return None
        if self._spec.on_value is not None:
            return self._matches(value, self._spec.on_value)
        return bool(value)


class MappingSwitch(MappingEntityBase, SwitchEntity):
    """Switch pairing a command property with a state property."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value()
        if value is None:
            return None
        if self._spec.on_value is not None:
            return self._matches(value, self._spec.on_value)
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        on_value = self._spec.on_value if self._spec.on_value is not None else 1
        await self._async_write(_norm(on_value))

    async def async_turn_off(self, **kwargs: Any) -> None:
        off_value = self._spec.off_value if self._spec.off_value is not None else 0
        await self._async_write(_norm(off_value))


class MappingLight(MappingEntityBase, LightEntity):
    """On/off light for a mapped command/state property pair."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value()
        if value is None:
            return None
        if self._spec.on_value is not None:
            return self._matches(value, self._spec.on_value)
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        on_value = self._spec.on_value if self._spec.on_value is not None else 1
        await self._async_write(_norm(on_value))

    async def async_turn_off(self, **kwargs: Any) -> None:
        off_value = self._spec.off_value if self._spec.off_value is not None else 0
        await self._async_write(_norm(off_value))


class MappingNumber(MappingEntityBase, NumberEntity):
    """Numeric setpoint for a mapped RW property."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self._spec.unit_of_measurement:
            self._attr_native_unit_of_measurement = self._spec.unit_of_measurement
        if self._spec.min_value is not None:
            self._attr_native_min_value = self._spec.min_value
        if self._spec.max_value is not None:
            self._attr_native_max_value = self._spec.max_value
        if self._spec.step is not None:
            self._attr_native_step = self._spec.step

    @property
    def native_value(self) -> float | None:
        value = self._raw_value()
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write(int(value) if value.is_integer() else value)


class MappingSelect(MappingEntityBase, SelectEntity):
    """Select for an enum-like RW property, with optional label mapping."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self._state_prop is None:
            # Same property read and written (the common enum case).
            self._state_prop = self._command_prop

    def _raw_to_label(self, value: Any) -> str:
        """Translate a raw property value to an option label."""
        raw = str(value)
        if self._spec.value_map:
            for label, mapped_raw in self._spec.value_map.items():
                if mapped_raw == raw:
                    return label
        return raw

    @property
    def current_option(self) -> str | None:
        value = self._raw_value()
        if value is None:
            return None
        return self._raw_to_label(value)

    @property
    def options(self) -> list[str]:
        """Spec options plus the current value when it isn't mapped."""
        values = list(self._spec.options)
        current = self.current_option
        if current and current not in values:
            values.append(current)
        return values

    async def async_select_option(self, option: str) -> None:
        value: Any = option
        if self._spec.value_map:
            value = self._spec.value_map.get(option, option)
        await self._async_write(_norm(value))


class MappingCover(MappingEntityBase, CoverEntity):
    """Cover driven by a state map and a toggle/command property."""

    _attr_device_class = CoverDeviceClass.GARAGE

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if self._spec.command_value == "timestamp":
            # Toggle-style covers (like the native GDO) also support STOP.
            self._attr_supported_features |= CoverEntityFeature.STOP

    def _translated_state(self) -> str | None:
        value = self._raw_value()
        if value is None:
            return None
        raw = str(value)
        if self._spec.state_map:
            return self._spec.state_map.get(raw, raw)
        return raw

    @property
    def _transition_states(self) -> tuple[str, ...]:
        return self._spec.transition_states or ("opening", "closing")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Sync transition tracking with the latest state, then notify HA."""
        state = self._translated_state()
        self.coordinator.set_device_transition_state(
            self._device.serial_number,
            state in self._transition_states,
        )
        super()._handle_coordinator_update()

    @property
    def is_closed(self) -> bool | None:
        state = self._translated_state()
        return state == "closed" if state is not None else None

    @property
    def is_opening(self) -> bool | None:
        return self._translated_state() == "opening"

    @property
    def is_closing(self) -> bool | None:
        return self._translated_state() == "closing"

    async def _async_command(self, fallback: Any) -> None:
        if self._spec.command_value == "timestamp":
            value: Any = str(int(time.time()))
        else:
            value = _norm(fallback)
        await self._async_write(value, refresh=False)
        self.coordinator.set_device_transition_state(self._device.serial_number, True)
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs: Any) -> None:
        on_value = self._spec.on_value if self._spec.on_value is not None else 1
        await self._async_command(on_value)

    async def async_close_cover(self, **kwargs: Any) -> None:
        off_value = self._spec.off_value if self._spec.off_value is not None else 0
        await self._async_command(off_value)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._async_command(self._spec.on_value)
