"""Mapping loader and resolver.

Public entry point: `resolve(device, store, bundled)` which merges bundled
JSON, user-store mappings, property-pattern matches, and user promotions into
a single `ResolvedMapping` for one device. The generic property dump is
appended separately by the classifier so this module stays pure.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .schema import (
    EntityMapping,
    Fanout,
    MappingsRootDict,
    ModelMappingDict,
    PropertyPatternDict,
    ResolvedMapping,
    validate_mapping,
)
from .store import MappingsStore, PromotionEntry

_LOGGER = logging.getLogger(__name__)

_BUNDLED_PATH = Path(__file__).parent / "bundled.json"


def load_bundled() -> MappingsRootDict:
    try:
        with _BUNDLED_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as err:
        _LOGGER.error("Failed to load bundled mappings: %s", err)
        return {"schema_version": 1, "models": {}, "property_patterns": []}
    data.setdefault("models", {})
    data.setdefault("property_patterns", [])
    return data


def _pattern_matches(pattern: PropertyPatternDict, properties_full: dict[str, Any]) -> bool:
    match = pattern.get("match", {})
    contains = match.get("properties_contain")
    if contains:
        if not isinstance(contains, list):
            return False
        if not all(name in properties_full for name in contains):
            return False
    return True


def _apply_promotions(
    entities: list[EntityMapping], promotions: dict[str, PromotionEntry]
) -> list[EntityMapping]:
    """Append a controllable entity per promotion. Promotions reference a
    property name; they don't replace existing entities, they add to the list.
    The caller (factory) will dedupe diagnostic sensors against state_property.
    """
    if not promotions:
        return entities
    out = list(entities)
    for prop_name, promo in promotions.items():
        kind = promo.get("kind")
        if kind is None:
            continue
        out.append(
            EntityMapping(
                kind=kind,
                state_property=prop_name,
                command_property=promo.get("command_property"),
                on_value=promo.get("on_value"),
                off_value=promo.get("off_value"),
                id_suffix=f"promoted_{prop_name}",
            )
        )
    return out


def resolve(
    oem_model_number: str,
    properties_full: dict[str, Any],
    store: MappingsStore,
    bundled: MappingsRootDict,
) -> ResolvedMapping:
    """Merge bundled + user store + property patterns + promotions into a
    ResolvedMapping for one device. Does NOT include the generic property
    dump - that's the classifier's job.
    """
    sources: list[str] = []
    entities: list[EntityMapping] = []
    fanout: Fanout | None = None
    display_name: str | None = None

    bundled_model = bundled.get("models", {}).get(oem_model_number)
    if bundled_model and validate_mapping(bundled_model):
        sources.append("bundled")
        display_name = bundled_model.get("display_name")
        if bundled_model.get("fanout"):
            fanout = Fanout.from_dict(bundled_model["fanout"])
        entities.extend(EntityMapping.from_dict(e) for e in bundled_model.get("entities", []))

    user_model: ModelMappingDict | None = store.get_mapping(oem_model_number)
    if user_model and validate_mapping(user_model):
        sources.append(user_model.get("source", "user"))
        display_name = user_model.get("display_name") or display_name
        if user_model.get("fanout"):
            fanout = Fanout.from_dict(user_model["fanout"])
        entities = [EntityMapping.from_dict(e) for e in user_model.get("entities", [])]

    for pattern in bundled.get("property_patterns", []):
        if _pattern_matches(pattern, properties_full):
            sources.append("pattern")
            entities.extend(EntityMapping.from_dict(e) for e in pattern.get("entities", []))

    promotions = store.get_promotions(oem_model_number)
    if promotions:
        sources.append("promotion")
        entities = _apply_promotions(entities, promotions)

    return ResolvedMapping(
        oem_model_number=oem_model_number,
        display_name=display_name,
        sources=sources,
        fanout=fanout,
        entities=entities,
    )
