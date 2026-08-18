"""Tests for the pure helpers in llm_client."""

import pytest

from custom_components.nomaiq.llm_client import (
    LLMClassificationError,
    build_instructions,
    build_property_table,
    build_retry_instructions,
    coerce_ai_task_result,
    extract_json_object,
    sanitize_mapping,
    summarize_mapping,
)
from tests.test_schema import GOLDEN_WATER_CONTROLLER


def _water_properties(units: int = 4) -> dict:
    props: dict = {}
    for n in range(1, units + 1):
        props[f"Unit{n}_Pairing_Status"] = {
            "base_type": "boolean",
            "read_only": True,
            "value": 1 if n <= 2 else 0,
        }
        props[f"Unit{n}_Manual_Switch"] = {
            "base_type": "integer",
            "read_only": False,
            "value": 0,
        }
        props[f"Unit{n}_Manual_SwitchStatus"] = {
            "base_type": "boolean",
            "read_only": True,
            "value": 0,
        }
        props[f"Unit{n}_Device_Name"] = {
            "base_type": "string",
            "read_only": True,
            "value": f"Zone {n}",
        }
    return props


class FakeDevice:
    oem_model_number = "water-controller"
    name = "Backyard Faucet"

    def __init__(self, props=None):
        self.properties_full = props if props is not None else _water_properties()

    def get_property_value(self, key):
        meta = self.properties_full.get(key)
        return meta.get("value") if isinstance(meta, dict) else False


# ---- extract_json_object ---------------------------------------------------


def test_extract_fenced_json():
    text = 'Here you go:\n```json\n{"display_name": "X"}\n```\nDone.'
    assert extract_json_object(text) == {"display_name": "X"}


def test_extract_fence_without_language_tag():
    text = '```\n{"a": 1}\n```'
    assert extract_json_object(text) == {"a": 1}


def test_extract_bare_json_with_prose():
    text = 'Sure! The mapping is {"a": {"b": 2}} which should work.'
    assert extract_json_object(text) == {"a": {"b": 2}}


def test_extract_nested_braces():
    text = '```json\n{"fanout": {"range": [1, 2]}, "entities": []}\n```'
    assert extract_json_object(text) == {"fanout": {"range": [1, 2]}, "entities": []}


def test_extract_garbage_raises():
    with pytest.raises(LLMClassificationError):
        extract_json_object("I could not determine a mapping, sorry.")


def test_extract_non_object_json_raises():
    with pytest.raises(LLMClassificationError):
        extract_json_object("[1, 2, 3]")


# ---- build_property_table ---------------------------------------------------


def test_property_table_marks_access_and_type():
    table = build_property_table(_water_properties())
    assert "Unit1_Manual_Switch | integer | RW | 0" in table
    assert "Unit1_Manual_SwitchStatus | boolean | RO | 0" in table


def test_property_table_truncates_long_values():
    table = build_property_table(
        {"blob": {"base_type": "string", "read_only": True, "value": "x" * 100}}
    )
    assert "x" * 41 not in table
    assert "…" in table


def test_property_table_skips_file_properties():
    table = build_property_table({"fw": {"base_type": "file", "read_only": True, "value": "data"}})
    assert "fw" not in table


def test_property_table_caps_rows():
    props = {
        f"prop_{i:03d}": {"base_type": "integer", "read_only": True, "value": i} for i in range(10)
    }
    table = build_property_table(props, max_rows=3)
    assert "7 more properties omitted" in table


def test_instructions_contain_device_and_rules():
    instructions = build_instructions(FakeDevice())
    assert "oem_model_number: water-controller" in instructions
    assert "Unit1_Manual_Switch" in instructions
    assert "RULES:" in instructions
    assert "sprinkler-x" in instructions  # few-shot example present
    # AI-task header demands raw JSON, not a fenced reply
    assert "fenced code block" not in instructions
    assert "Output only JSON" in instructions


def test_retry_instructions_include_feedback():
    retry = build_retry_instructions(FakeDevice(), '{"bad": 1}', "missing entities")
    assert '{"bad": 1}' in retry
    assert "missing entities" in retry
    assert retry.endswith("Reply again with ONLY the corrected JSON object.")


# ---- coerce_ai_task_result ---------------------------------------------------


def test_coerce_dict_passthrough():
    assert coerce_ai_task_result({"a": 1}) == {"a": 1}


def test_coerce_json_string():
    assert coerce_ai_task_result('{"a": 1}') == {"a": 1}


def test_coerce_fenced_string():
    assert coerce_ai_task_result('```json\n{"a": 1}\n```') == {"a": 1}


def test_coerce_garbage_string_raises():
    with pytest.raises(LLMClassificationError):
        coerce_ai_task_result("no json here")


def test_coerce_list_raises():
    with pytest.raises(LLMClassificationError):
        coerce_ai_task_result([1, 2, 3])


# ---- summarize_mapping --------------------------------------------------------


def test_summarize_mixed_kinds_pluralized():
    mapping = {
        "entities": [
            {"kind": "switch"},
            {"kind": "number"},
            {"kind": "number"},
            {"kind": "binary_sensor"},
            {"kind": "sensor"},
            {"kind": "sensor"},
            {"kind": "sensor"},
        ]
    }
    assert summarize_mapping(mapping) == "1 switch, 2 numbers, 1 binary sensor, 3 sensors"


def test_summarize_with_fanout_suffix():
    mapping = {
        "entities": [{"kind": "switch"}],
        "fanout": {"range": [1, 2, 3, 4]},
    }
    assert summarize_mapping(mapping) == "1 switch — fanned out over 4 units"


def test_summarize_empty():
    assert summarize_mapping({"entities": []}) == "no entities"


# ---- sanitize_mapping --------------------------------------------------------


def test_sanitize_accepts_golden_mapping():
    mapping = sanitize_mapping(dict(GOLDEN_WATER_CONTROLLER), _water_properties())
    assert mapping["source"] == "llm"
    assert mapping["fanout"]["range"] == [1, 2, 3, 4]
    assert len(mapping["entities"]) == 1


def test_sanitize_shrinks_fanout_range():
    raw = dict(GOLDEN_WATER_CONTROLLER)
    raw["fanout"] = dict(raw["fanout"], range=[1, 2, 3, 4, 5, 6, 7, 8])
    mapping = sanitize_mapping(raw, _water_properties(units=4))
    assert mapping["fanout"]["range"] == [1, 2, 3, 4]


def test_sanitize_rejects_invented_properties():
    raw = {
        "entities": [
            {"kind": "sensor", "state_property": "made_up_property"},
        ]
    }
    with pytest.raises(LLMClassificationError):
        sanitize_mapping(raw, _water_properties())


def test_sanitize_rejects_read_only_command():
    raw = {
        "entities": [
            {
                "kind": "switch",
                "state_property": "Unit1_Manual_SwitchStatus",
                "command_property": "Unit1_Manual_SwitchStatus",  # RO
            }
        ]
    }
    with pytest.raises(LLMClassificationError):
        sanitize_mapping(raw, _water_properties())


def test_sanitize_keeps_valid_drops_invalid():
    raw = {
        "entities": [
            {"kind": "sensor", "state_property": "Unit1_Manual_SwitchStatus"},
            {"kind": "sensor", "state_property": "nope"},
        ]
    }
    mapping = sanitize_mapping(raw, _water_properties())
    assert len(mapping["entities"]) == 1


def test_sanitize_unwraps_models_envelope():
    raw = {"models": {"water-controller": dict(GOLDEN_WATER_CONTROLLER)}}
    mapping = sanitize_mapping(raw, _water_properties())
    assert mapping["entities"]


def test_sanitize_rejects_schema_violation():
    raw = {"entities": [{"kind": "switch", "state_property": "Unit1_Manual_SwitchStatus"}]}
    # switch without command_property fails validate_mapping
    with pytest.raises(LLMClassificationError):
        sanitize_mapping(raw, _water_properties())


def _number_entity(**range_fields):
    return {
        "kind": "number",
        "state_property": "Unit1_Manual_Switch",
        "command_property": "Unit1_Manual_Switch",
        **range_fields,
    }


def test_sanitize_keeps_valid_number_range():
    raw = {"entities": [_number_entity(min_value=0, max_value=240, step=5)]}
    mapping = sanitize_mapping(raw, _water_properties())
    entity = mapping["entities"][0]
    assert entity["min_value"] == 0
    assert entity["max_value"] == 240
    assert entity["step"] == 5


def test_sanitize_strips_inverted_number_range():
    raw = {"entities": [_number_entity(min_value=100, max_value=0)]}
    mapping = sanitize_mapping(raw, _water_properties())
    entity = mapping["entities"][0]
    assert "min_value" not in entity
    assert "max_value" not in entity


def test_sanitize_strips_nonpositive_step():
    raw = {"entities": [_number_entity(min_value=0, max_value=100, step=-1)]}
    mapping = sanitize_mapping(raw, _water_properties())
    entity = mapping["entities"][0]
    assert "step" not in entity
    assert "min_value" not in entity  # whole triple stripped together
