"""Tests for the mapping schema validation."""

from custom_components.nomaiq.mappings.schema import validate_mapping

GOLDEN_WATER_CONTROLLER = {
    "display_name": "Water Controller",
    "source": "llm",
    "fanout": {
        "range": [1, 2, 3, 4],
        "gate_property": "Unit{n}_Pairing_Status",
        "name_property": "Unit{n}_Device_Name",
        "name_fallback": "{device_name} Unit {n}",
    },
    "entities": [
        {
            "kind": "switch",
            "id_suffix": "unit{n}_manual",
            "state_property": "Unit{n}_Manual_SwitchStatus",
            "command_property": "Unit{n}_Manual_Switch",
            "on_value": 1,
            "off_value": 0,
        }
    ],
}


def test_golden_water_controller_mapping_is_valid():
    assert validate_mapping(GOLDEN_WATER_CONTROLLER)


def test_switch_without_command_property_is_invalid():
    assert not validate_mapping({"entities": [{"kind": "switch", "state_property": "x"}]})


def test_switch_without_state_property_is_invalid():
    assert not validate_mapping({"entities": [{"kind": "switch", "command_property": "x"}]})


def test_unknown_kind_is_invalid():
    assert not validate_mapping({"entities": [{"kind": "valve", "state_property": "x"}]})


def test_bad_command_value_is_invalid():
    assert not validate_mapping(
        {
            "entities": [
                {
                    "kind": "cover",
                    "state_property": "s",
                    "command_property": "c",
                    "command_value": "magic",
                }
            ]
        }
    )


def test_cover_requires_state_and_command():
    assert not validate_mapping({"entities": [{"kind": "cover", "state_property": "s"}]})


def test_non_integer_fanout_range_is_invalid():
    assert not validate_mapping({"entities": [], "fanout": {"range": ["1", "2"]}})


def test_sensor_only_mapping_is_valid():
    assert validate_mapping({"entities": [{"kind": "sensor", "state_property": "rssi"}]})


def test_non_dict_is_invalid():
    assert not validate_mapping(["not", "a", "mapping"])
