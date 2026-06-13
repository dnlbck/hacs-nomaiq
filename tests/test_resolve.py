"""Tests for the mapping resolution merge."""

from custom_components.nomaiq.mappings import resolve
from tests.test_schema import GOLDEN_WATER_CONTROLLER

EMPTY_BUNDLED = {"schema_version": 1, "models": {}, "property_patterns": []}


class FakeStore:
    def __init__(self, mapping=None, promotions=None):
        self._mapping = mapping
        self._promotions = promotions or {}

    def get_mapping(self, oem_model):
        return self._mapping

    def get_promotions(self, oem_model):
        return self._promotions


def test_resolve_with_no_sources_is_empty():
    resolved = resolve("mystery", {}, FakeStore(), EMPTY_BUNDLED)
    assert resolved.entities == []
    assert resolved.fanout is None
    assert resolved.sources == []


def test_resolve_uses_stored_llm_mapping():
    resolved = resolve(
        "water-controller", {}, FakeStore(mapping=GOLDEN_WATER_CONTROLLER), EMPTY_BUNDLED
    )
    assert resolved.sources == ["llm"]
    assert resolved.display_name == "Water Controller"
    assert resolved.fanout is not None
    assert resolved.fanout.range == (1, 2, 3, 4)
    assert resolved.fanout.gate_property == "Unit{n}_Pairing_Status"
    assert len(resolved.entities) == 1
    assert resolved.entities[0].kind == "switch"
    assert resolved.entities[0].command_property == "Unit{n}_Manual_Switch"


def test_resolve_ignores_invalid_stored_mapping():
    bad = {"entities": [{"kind": "valve", "state_property": "x"}]}
    resolved = resolve("mystery", {}, FakeStore(mapping=bad), EMPTY_BUNDLED)
    assert resolved.entities == []


def test_resolve_applies_promotions():
    promotions = {
        "pump_state": {"kind": "switch", "command_property": "pump_cmd", "on_value": 1}
    }
    resolved = resolve("mystery", {}, FakeStore(promotions=promotions), EMPTY_BUNDLED)
    assert resolved.sources == ["promotion"]
    assert len(resolved.entities) == 1
    promoted = resolved.entities[0]
    assert promoted.kind == "switch"
    assert promoted.state_property == "pump_state"
    assert promoted.command_property == "pump_cmd"
    assert promoted.id_suffix == "promoted_pump_state"


def test_resolve_bundled_property_pattern():
    bundled = {
        "schema_version": 1,
        "models": {},
        "property_patterns": [
            {
                "match": {"properties_contain": ["rssi"]},
                "entities": [{"kind": "sensor", "state_property": "rssi"}],
            }
        ],
    }
    resolved = resolve("mystery", {"rssi": {}}, FakeStore(), bundled)
    assert resolved.sources == ["pattern"]
    assert resolved.entities[0].state_property == "rssi"

    resolved_no_match = resolve("mystery", {"other": {}}, FakeStore(), bundled)
    assert resolved_no_match.entities == []
