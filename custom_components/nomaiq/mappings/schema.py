"""Mapping schema for nomaiq LLM device classification.

Defines the JSON shape that describes how a Noma IQ device is projected into
Home Assistant entities. Used both for loading bundled/user-stored mappings and
for validating mappings returned by the LLM classifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

SCHEMA_VERSION = 1

EntityKind = Literal["sensor", "binary_sensor", "switch", "light", "cover", "number", "select"]

VALID_KINDS: frozenset[str] = frozenset(
    {"sensor", "binary_sensor", "switch", "light", "cover", "number", "select"}
)

VALID_COMMAND_VALUES: frozenset[str] = frozenset({"timestamp"})


class EntityMappingDict(TypedDict, total=False):
    """Serialised form of an entity definition."""

    kind: str
    id_suffix: str
    state_property: str
    command_property: str
    on_value: Any
    off_value: Any
    state_map: dict[str, str]
    transition_states: list[str]
    name_property: str
    name_fallback: str
    device_class: str
    unit_of_measurement: str
    entity_category: str
    supported_features: list[str]
    command_value: str
    min_value: float
    max_value: float
    step: float
    options: list[str]
    value_map: dict[str, str]


class FanoutDict(TypedDict, total=False):
    range: list[int]
    gate_property: str
    name_property: str
    name_fallback: str


class ModelMappingDict(TypedDict, total=False):
    display_name: str
    source: str
    fanout: FanoutDict
    entities: list[EntityMappingDict]


class PropertyPatternDict(TypedDict):
    match: dict[str, Any]
    entities: list[EntityMappingDict]


class MappingsRootDict(TypedDict):
    schema_version: int
    models: dict[str, ModelMappingDict]
    property_patterns: list[PropertyPatternDict]


@dataclass(frozen=True)
class EntityMapping:
    """Resolved entity definition."""

    kind: str
    id_suffix: str | None = None
    state_property: str | None = None
    command_property: str | None = None
    on_value: Any = None
    off_value: Any = None
    state_map: dict[str, str] | None = None
    transition_states: tuple[str, ...] = ()
    name_property: str | None = None
    name_fallback: str | None = None
    device_class: str | None = None
    unit_of_measurement: str | None = None
    entity_category: str | None = None
    supported_features: tuple[str, ...] = ()
    command_value: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options: tuple[str, ...] = ()
    value_map: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: EntityMappingDict) -> EntityMapping:
        return cls(
            kind=data["kind"],
            id_suffix=data.get("id_suffix"),
            state_property=data.get("state_property"),
            command_property=data.get("command_property"),
            on_value=data.get("on_value"),
            off_value=data.get("off_value"),
            state_map=data.get("state_map"),
            transition_states=tuple(data.get("transition_states", ())),
            name_property=data.get("name_property"),
            name_fallback=data.get("name_fallback"),
            device_class=data.get("device_class"),
            unit_of_measurement=data.get("unit_of_measurement"),
            entity_category=data.get("entity_category"),
            supported_features=tuple(data.get("supported_features", ())),
            command_value=data.get("command_value"),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            step=data.get("step"),
            options=tuple(data.get("options", ())),
            value_map=data.get("value_map"),
        )


@dataclass(frozen=True)
class Fanout:
    range: tuple[int, ...]
    gate_property: str | None = None
    name_property: str | None = None
    name_fallback: str | None = None

    @classmethod
    def from_dict(cls, data: FanoutDict) -> Fanout:
        return cls(
            range=tuple(data.get("range", ())),
            gate_property=data.get("gate_property"),
            name_property=data.get("name_property"),
            name_fallback=data.get("name_fallback"),
        )


@dataclass
class ResolvedMapping:
    """Per-device resolved mapping. Consumed by the factory."""

    oem_model_number: str
    display_name: str | None = None
    sources: list[str] = field(default_factory=list)
    fanout: Fanout | None = None
    entities: list[EntityMapping] = field(default_factory=list)


def validate_mapping(data: Any) -> bool:
    """Validate a ModelMappingDict-shaped value. Used on LLM output and on
    bundled JSON at load. Returns True only if the structure is sound enough
    to instantiate entities from.
    """
    if not isinstance(data, dict):
        return False
    entities = data.get("entities")
    if entities is None:
        return True
    if not isinstance(entities, list):
        return False
    for entity in entities:
        if not isinstance(entity, dict):
            return False
        kind = entity.get("kind")
        if kind not in VALID_KINDS:
            return False
        state_prop = entity.get("state_property")
        command_prop = entity.get("command_property")
        if state_prop is not None and not isinstance(state_prop, str):
            return False
        if command_prop is not None and not isinstance(command_prop, str):
            return False
        command_value = entity.get("command_value")
        if command_value is not None and command_value not in VALID_COMMAND_VALUES:
            return False
        for range_field in ("min_value", "max_value", "step"):
            field_value = entity.get(range_field)
            if field_value is not None and (
                isinstance(field_value, bool) or not isinstance(field_value, (int, float))
            ):
                return False
        if kind in {"switch", "light", "binary_sensor"} and state_prop is None:
            return False
        if kind in {"switch", "light"} and command_prop is None:
            return False
        if kind == "cover":
            if state_prop is None or command_prop is None:
                return False
            state_map = entity.get("state_map")
            if state_map is not None and not isinstance(state_map, dict):
                return False
        if kind == "select":
            if command_prop is None:
                return False
            options = entity.get("options")
            if (
                not isinstance(options, list)
                or not options
                or not all(isinstance(option, str) for option in options)
            ):
                return False
            value_map = entity.get("value_map")
            if value_map is not None and not (
                isinstance(value_map, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in value_map.items())
            ):
                return False
    fanout = data.get("fanout")
    if fanout is not None:
        if not isinstance(fanout, dict):
            return False
        rng = fanout.get("range")
        if rng is not None and not (isinstance(rng, list) and all(isinstance(n, int) for n in rng)):
            return False
    return True
