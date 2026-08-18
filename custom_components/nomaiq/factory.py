"""Build mapping-driven entities and wire platforms to late classification.

`build_entities` turns a ResolvedMapping into entity instances for one
platform. `async_setup_mapped_platform` is shared glue each mapped platform
calls from async_setup_entry: it adds entities for devices already resolved
and subscribes to the dispatcher signal for devices classified later.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import ayla_iot_unofficial.device
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_NEW_MAPPED_ENTITIES
from .coordinator import NomaIQDataUpdateCoordinator
from .mapping_entities import (
    MappingBinarySensor,
    MappingCover,
    MappingEntityBase,
    MappingLight,
    MappingNumber,
    MappingSelect,
    MappingSensor,
    MappingSwitch,
    format_template,
)
from .mappings.schema import EntityMapping, ResolvedMapping

if TYPE_CHECKING:
    from . import NomaIQConfigEntry

_LOGGER = logging.getLogger(__name__)

KIND_TO_PLATFORM: dict[str, Platform] = {
    "sensor": Platform.SENSOR,
    "binary_sensor": Platform.BINARY_SENSOR,
    "switch": Platform.SWITCH,
    "light": Platform.LIGHT,
    "cover": Platform.COVER,
    "number": Platform.NUMBER,
    "select": Platform.SELECT,
}

_KIND_TO_CLASS: dict[str, type[MappingEntityBase]] = {
    "sensor": MappingSensor,
    "binary_sensor": MappingBinarySensor,
    "switch": MappingSwitch,
    "light": MappingLight,
    "cover": MappingCover,
    "number": MappingNumber,
    "select": MappingSelect,
}


def _is_fanout_spec(spec: EntityMapping) -> bool:
    return any(
        "{n}" in value
        for value in (
            spec.id_suffix,
            spec.state_property,
            spec.command_property,
            spec.name_property,
        )
        if value
    )


def build_entities(
    coordinator: NomaIQDataUpdateCoordinator,
    device: ayla_iot_unofficial.device.Device,
    resolved: ResolvedMapping,
    platform: Platform,
) -> list[MappingEntityBase]:
    """Instantiate this platform's entities for one device's resolved mapping."""
    entities: list[MappingEntityBase] = []
    seen_unique_ids: set[str] = set()
    fanout = resolved.fanout

    for spec in resolved.entities:
        if KIND_TO_PLATFORM.get(spec.kind) is not platform:
            continue
        entity_class = _KIND_TO_CLASS[spec.kind]

        if _is_fanout_spec(spec):
            if fanout is None:
                _LOGGER.debug(
                    "Skipping fanout spec %s for %s: mapping has no fanout block",
                    spec.id_suffix or spec.state_property,
                    resolved.oem_model_number,
                )
                continue
            # Inherit per-unit naming from the fanout block when the spec
            # doesn't define its own.
            if spec.name_property is None and fanout.name_property:
                spec = replace(spec, name_property=fanout.name_property)
            if spec.name_fallback is None and fanout.name_fallback:
                spec = replace(spec, name_fallback=fanout.name_fallback)
            for n in fanout.range:
                if fanout.gate_property:
                    # format_template never raises on malformed templates (e.g. from a
                    # hand-edited user mapping); an unresolvable gate reads as
                    # a missing property, i.e. the unit is skipped.
                    gate = format_template(fanout.gate_property, {"n": n})
                    if not gate or not bool(device.get_property_value(gate)):
                        continue
                entities.append(entity_class(coordinator, device, spec, {"n": n}))
        else:
            entities.append(entity_class(coordinator, device, spec))

    deduped: list[MappingEntityBase] = []
    for entity in entities:
        if entity.unique_id in seen_unique_ids:
            _LOGGER.warning(
                "Dropping duplicate mapped entity %s for device %s",
                entity.unique_id,
                device.serial_number,
            )
            continue
        seen_unique_ids.add(entity.unique_id)
        deduped.append(entity)
    return deduped


@callback
def async_setup_mapped_platform(
    hass: HomeAssistant,
    entry: NomaIQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform: Platform,
) -> None:
    """Add mapped entities for resolved devices and listen for late arrivals."""
    coordinator = entry.runtime_data
    manager = coordinator.adoption
    if manager is None:
        return

    def _build(serial: str) -> list[MappingEntityBase]:
        device = coordinator.get_device(serial)
        resolved = manager.resolved.get(serial)
        if device is None or resolved is None:
            return []
        return build_entities(coordinator, device, resolved, platform)

    initial = [entity for serial in list(manager.resolved) for entity in _build(serial)]
    if initial:
        async_add_entities(initial, update_before_add=False)

    @callback
    def _async_new_mapped(serial: str) -> None:
        new_entities = _build(serial)
        if new_entities:
            async_add_entities(new_entities, update_before_add=False)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_MAPPED_ENTITIES.format(entry_id=entry.entry_id),
            _async_new_mapped,
        )
    )
