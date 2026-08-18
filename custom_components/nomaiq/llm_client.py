"""Classify a device's properties into a mapping via a Home Assistant AI Task.

The instructions, JSON extraction, and sanitation helpers are pure functions
so they can be unit-tested without a running Home Assistant; all
homeassistant.components imports are function-local. `async_classify_device`
is the only entry point with side effects (it runs the AI task); persisting
results is the AdoptionManager's job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from typing import Any

import ayla_iot_unofficial.device
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import AI_TASK_TIMEOUT_SECONDS, MAX_PROMPT_PROPERTIES
from .mappings.schema import ModelMappingDict, validate_mapping

_LOGGER = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class LLMClassificationError(HomeAssistantError):
    """The AI task could not produce a usable mapping."""


def build_property_table(
    properties_full: dict[str, Any], max_rows: int = MAX_PROMPT_PROPERTIES
) -> str:
    """Render properties as 'name | type | RO/RW | value' rows for the prompt."""
    rows: list[str] = []
    omitted = 0
    for name in sorted(properties_full):
        meta = properties_full[name]
        if not isinstance(meta, dict):
            meta = {}
        if meta.get("base_type") == "file":
            continue
        if len(rows) >= max_rows:
            omitted += 1
            continue
        access = "RO" if meta.get("read_only") else "RW"
        value = str(meta.get("value"))
        if len(value) > 40:
            value = value[:40] + "…"
        rows.append(f"  {name} | {meta.get('base_type', '?')} | {access} | {value}")
    if omitted:
        rows.append(f"  … {omitted} more properties omitted")
    return "\n".join(rows)


_PROMPT_BODY = """
Respond with a JSON object of this shape (omit any field you don't need):
{
  "display_name": "<human readable model name>",
  "fanout": {
    "range": [1, 2, 3, 4],
    "gate_property": "<per-unit property whose truthy value means the unit exists>",
    "name_property": "<per-unit property holding the unit's name>",
    "name_fallback": "{device_name} Unit {n}"
  },
  "entities": [
    {
      "kind": "sensor" | "binary_sensor" | "switch" | "light" | "cover" | "number" | "select",
      "id_suffix": "<short unique snake_case id, may contain {n}>",
      "state_property": "<property name>",
      "command_property": "<property name; required for switch/light/cover/number/select>",
      "on_value": 1,
      "off_value": 0,
      "state_map": {"<raw value>": "opened|closed|opening|closing"},
      "transition_states": ["opening", "closing"],
      "command_value": "timestamp",
      "options": ["<option label>", "..."],
      "value_map": {"<option label>": "<raw value written to command_property>"},
      "name_property": "<optional>",
      "name_fallback": "<optional>",
      "device_class": "<optional HA device class>",
      "unit_of_measurement": "<optional>",
      "min_value": "<optional number, kind=number only>",
      "max_value": "<optional number, kind=number only>",
      "step": "<optional number, kind=number only>",
      "entity_category": "diagnostic"
    }
  ]
}

RULES:
1. Use ONLY property names that appear in the PROPERTIES table. Never invent names.
2. access=RO properties may only be state_property. command_property MUST be access=RW.
3. Controllable features usually pair an RW command property with an RO status property
   (e.g. X_Switch is RW and X_SwitchStatus is RO): use the RW one as command_property
   and the RO one as state_property.
4. If numbered groups repeat (Unit1_*, Unit2_*, ...), output ONE entity definition using
   {n} placeholders plus a "fanout" block. Omit "fanout" entirely when nothing repeats.
5. If you are unsure whether something is safely controllable, use kind "sensor".
6. boolean state -> binary_sensor (or switch when a matching RW command exists);
   numeric/string telemetry -> sensor; numeric setpoint with RW access -> number.
7. Skip pure-infrastructure properties (firmware versions, rssi, schedules, raw error
   registers) or include them with "entity_category": "diagnostic".
8. "command_value": "timestamp" is ONLY for cover-style toggle commands that expect a
   unix-timestamp string write.
9. For kind "number", set min_value/max_value/step when a plausible range is inferable
   from the property name, unit, or current value (e.g. a humidity % setpoint -> 30-80,
   step 1). Omit them when unknown, and never output a range that excludes the
   property's current value.
10. Use kind "select" for an RW enum-like property (mode, fan speed, ...) only when you
    can enumerate plausible option labels, and always include the property's current
    value in options. Set value_map only when the raw values differ from the labels
    (e.g. labels "Low"/"High" backed by raw values "0"/"1").
11. Allowed kinds are exactly the seven listed. Never output climate, fan, valve, or
    humidifier.

EXAMPLE for a different device (model "sprinkler-x" with properties: Zone1_Installed RO
boolean, Zone1_Run RW integer, Zone1_Run_Status RO boolean, Zone1_Label RO string, and
the same for Zone2):
```json
{"display_name": "Sprinkler X",
 "fanout": {"range": [1, 2], "gate_property": "Zone{n}_Installed",
            "name_property": "Zone{n}_Label", "name_fallback": "{device_name} Zone {n}"},
 "entities": [{"kind": "switch", "id_suffix": "zone{n}_run",
               "state_property": "Zone{n}_Run_Status", "command_property": "Zone{n}_Run",
               "on_value": 1, "off_value": 0}]}
```

Now produce the JSON for the DEVICE above.
"""


def build_instructions(device: ayla_iot_unofficial.device.Device) -> str:
    """Build the AI task instructions for one device."""
    return (
        "You are classifying an IoT device's cloud API properties into Home Assistant "
        "entities.\nReturn a single JSON object that follows the shape described "
        "below. Output only JSON — no explanations, no prose.\n\n"
        "DEVICE:\n"
        f"  oem_model_number: {device.oem_model_number}\n"
        f"  device_name: {device.name}\n\n"
        "PROPERTIES (name | type | access | current value):\n"
        f"{build_property_table(device.properties_full)}\n"
        f"{_PROMPT_BODY}"
    )


def build_retry_instructions(
    device: ayla_iot_unofficial.device.Device, previous_reply: str, error: str
) -> str:
    """Build the one-shot retry instructions with feedback about the failure."""
    return (
        f"{build_instructions(device)}\n\n"
        f"Your previous reply was:\n{previous_reply}\n\n"
        f"It could not be used because: {error}\n"
        "Reply again with ONLY the corrected JSON object."
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first parseable JSON object out of a text reply."""
    candidates = [match.group(1) for match in _JSON_FENCE_RE.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMClassificationError("reply contained no parseable JSON object")


def coerce_ai_task_result(data: Any) -> dict[str, Any]:
    """Normalize GenDataTaskResult.data into a dict.

    Providers with real structured output return a parsed dict; loose-JSON
    providers (e.g. Mistral's json_object mode) may return a string.
    """
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        return extract_json_object(data)
    raise LLMClassificationError(f"AI task returned unsupported data type {type(data).__name__}")


_KIND_ORDER = ("switch", "light", "cover", "number", "select", "binary_sensor", "sensor")


def summarize_mapping(mapping: dict[str, Any]) -> str:
    """Human one-liner for the preview step: '1 switch, 2 numbers, 9 sensors'."""
    counts = Counter(
        entity.get("kind") for entity in mapping.get("entities", []) if isinstance(entity, dict)
    )
    parts: list[str] = []
    for kind in _KIND_ORDER:
        count = counts.get(kind, 0)
        if not count:
            continue
        label = kind.replace("_", " ")
        parts.append(f"{count} {label}{'s' if count != 1 else ''}")
    summary = ", ".join(parts) if parts else "no entities"
    fanout = mapping.get("fanout") or {}
    fanout_range = fanout.get("range") or []
    if fanout_range:
        summary += f" — fanned out over {len(fanout_range)} units"
    return summary


def _format_n(template: str, n: int) -> str | None:
    """Format a {n} template defensively; None when the template is malformed."""
    try:
        return template.replace("{n}", str(n))
    except Exception:
        return None


def _property_exists(properties_full: dict[str, Any], name: str | None) -> bool:
    return bool(name) and name in properties_full


def _property_writable(properties_full: dict[str, Any], name: str) -> bool:
    meta = properties_full.get(name)
    return isinstance(meta, dict) and not meta.get("read_only")


def _strip_invalid_number_range(entity: dict[str, Any]) -> dict[str, Any]:
    """Drop an invalid min/max/step triple from a number entity, keeping the entity."""
    min_value = entity.get("min_value")
    max_value = entity.get("max_value")
    step = entity.get("step")
    invalid = (min_value is not None and max_value is not None and min_value >= max_value) or (
        step is not None and step <= 0
    )
    if not invalid:
        return entity
    _LOGGER.debug("Dropping invalid number range on entity %r", entity.get("id_suffix"))
    return {k: v for k, v in entity.items() if k not in ("min_value", "max_value", "step")}


def sanitize_mapping(
    raw: dict[str, Any], properties_full: dict[str, Any]
) -> tuple[ModelMappingDict, list[str]]:
    """Validate AI output against the device's real properties.

    Drops entities referencing nonexistent properties, requires command
    properties to be writable, and shrinks the fanout range to units whose
    properties actually exist. Returns the sanitized mapping plus
    human-readable reasons for every dropped entity. Raises
    LLMClassificationError when nothing usable survives, with reasons
    suitable for the retry instructions.
    """
    if not isinstance(raw, dict):
        raise LLMClassificationError("top-level JSON value is not an object")

    # Some models wrap the answer in {"models": {"<model>": {...}}}.
    if "entities" not in raw and isinstance(raw.get("models"), dict) and len(raw["models"]) == 1:
        raw = next(iter(raw["models"].values()))
        if not isinstance(raw, dict):
            raise LLMClassificationError("wrapped model value is not an object")

    mapping: dict[str, Any] = dict(raw)
    mapping["source"] = "llm"
    if mapping.get("fanout") is None:
        mapping.pop("fanout", None)

    if not validate_mapping(mapping):
        raise LLMClassificationError(
            "JSON does not match the mapping schema (check kinds and required "
            "state_property/command_property fields)"
        )

    entities = mapping.get("entities") or []
    if not entities:
        raise LLMClassificationError("mapping contains no entities")

    fanout = mapping.get("fanout")
    fanout_range: list[int] = list(fanout.get("range", [])) if fanout else []
    errors: list[str] = []

    def _spec_props(entity: dict[str, Any]) -> tuple[str | None, str | None]:
        return entity.get("state_property"), entity.get("command_property")

    def _is_fanout_entity(entity: dict[str, Any]) -> bool:
        return any(
            "{n}" in value
            for value in (
                entity.get("id_suffix"),
                entity.get("state_property"),
                entity.get("command_property"),
                entity.get("name_property"),
            )
            if isinstance(value, str)
        )

    fanout_entities = [e for e in entities if _is_fanout_entity(e)]

    # Shrink the fanout range to units whose state/command properties exist.
    if fanout_entities and fanout_range:
        valid_ns: list[int] = []
        for n in fanout_range:
            ok = True
            for entity in fanout_entities:
                state_prop, command_prop = _spec_props(entity)
                if state_prop and "{n}" in state_prop:
                    formatted = _format_n(state_prop, n)
                    if not _property_exists(properties_full, formatted):
                        ok = False
                if command_prop and "{n}" in command_prop:
                    formatted = _format_n(command_prop, n)
                    if not _property_exists(properties_full, formatted) or not _property_writable(
                        properties_full, formatted
                    ):
                        ok = False
            if ok:
                valid_ns.append(n)
        if not valid_ns:
            errors.append("no fanout unit has all referenced properties present and writable")
        elif valid_ns != fanout_range:
            _LOGGER.debug("Shrinking fanout range %s -> %s", fanout_range, valid_ns)
        fanout_range = valid_ns
        if fanout is not None:
            fanout = dict(fanout)
            fanout["range"] = valid_ns
            gate = fanout.get("gate_property")
            if gate and not any(
                _property_exists(properties_full, _format_n(gate, n)) for n in valid_ns
            ):
                _LOGGER.warning("Dropping nonexistent gate_property %r", gate)
                fanout.pop("gate_property", None)
            name_prop = fanout.get("name_property")
            if name_prop and not any(
                _property_exists(properties_full, _format_n(name_prop, n)) for n in valid_ns
            ):
                fanout.pop("name_property", None)
            mapping["fanout"] = fanout
    elif fanout_entities and not fanout_range:
        errors.append("entities use {n} placeholders but fanout.range is missing")

    kept: list[dict[str, Any]] = []
    for entity in entities:
        if entity.get("kind") == "number":
            entity = _strip_invalid_number_range(entity)
        state_prop, command_prop = _spec_props(entity)
        if _is_fanout_entity(entity):
            if fanout_range:
                kept.append(entity)
            continue
        if state_prop and not _property_exists(properties_full, state_prop):
            errors.append(f"state_property {state_prop!r} does not exist")
            continue
        if command_prop:
            if not _property_exists(properties_full, command_prop):
                errors.append(f"command_property {command_prop!r} does not exist")
                continue
            if not _property_writable(properties_full, command_prop):
                errors.append(f"command_property {command_prop!r} is read-only (RO)")
                continue
        if not state_prop and not command_prop:
            errors.append(f"entity {entity.get('id_suffix')!r} references no properties")
            continue
        name_prop = entity.get("name_property")
        if name_prop and not _property_exists(properties_full, name_prop):
            entity = {k: v for k, v in entity.items() if k != "name_property"}
        kept.append(entity)

    if not kept:
        raise LLMClassificationError(
            "no usable entities survived validation: " + "; ".join(errors[:8])
        )
    for error in errors:
        _LOGGER.debug("Dropped part of AI mapping: %s", error)
    mapping["entities"] = kept
    return mapping, errors  # type: ignore[return-value]


def _ai_task_structure() -> dict[str, Any]:
    """Top-level structure hint for ai_task.async_generate_data.

    Nested typing isn't expressible with selectors, so the detailed contract
    lives in the instructions and sanitize_mapping stays the enforcement
    layer. Imported lazily so this module stays importable without HA.
    """
    from homeassistant.helpers import selector

    return {
        "display_name": {
            "description": "Human readable model name",
            "required": True,
            "selector": selector.TextSelector(selector.TextSelectorConfig()),
        },
        "fanout": {
            "description": (
                "Fanout block for repeating Unit{n}_ style properties; omit when nothing repeats"
            ),
            "required": False,
            "selector": selector.ObjectSelector(selector.ObjectSelectorConfig()),
        },
        "entities": {
            "description": (
                "List of entity definition objects per the contract in the instructions"
            ),
            "required": True,
            "selector": selector.ObjectSelector(selector.ObjectSelectorConfig()),
        },
    }


async def _generate_data(
    hass: HomeAssistant,
    device: ayla_iot_unofficial.device.Device,
    instructions: str,
    entity_id: str,
) -> Any:
    """Run one AI task and return its raw data payload."""
    from homeassistant.components import ai_task

    try:
        async with asyncio.timeout(AI_TASK_TIMEOUT_SECONDS):
            result = await ai_task.async_generate_data(
                hass,
                task_name=f"NomaIQ classify {device.oem_model_number}",
                entity_id=entity_id,
                instructions=instructions,
                structure=_ai_task_structure(),
            )
    except TimeoutError as err:
        raise LLMClassificationError(f"AI task timed out after {AI_TASK_TIMEOUT_SECONDS}s") from err
    except asyncio.CancelledError:
        raise
    except Exception as err:
        raise LLMClassificationError(f"AI task failed: {err}") from err
    return result.data


async def async_classify_device(
    hass: HomeAssistant,
    device: ayla_iot_unofficial.device.Device,
    entity_id: str,
) -> tuple[ModelMappingDict, list[str]]:
    """Ask the AI task entity to map this device; one retry with feedback.

    Returns the sanitized mapping plus reasons for any entities dropped
    during validation.
    """
    last_error = ""
    last_reply = ""
    for attempt in range(2):
        if attempt == 0:
            instructions = build_instructions(device)
        else:
            instructions = build_retry_instructions(device, last_reply, last_error)
        try:
            data = await _generate_data(hass, device, instructions, entity_id)
            last_reply = data if isinstance(data, str) else json.dumps(data, default=str)
            raw = coerce_ai_task_result(data)
            mapping, dropped = sanitize_mapping(raw, device.properties_full)
        except LLMClassificationError as err:
            last_error = str(err)
            _LOGGER.debug(
                "Classification attempt %d for %s failed: %s",
                attempt + 1,
                device.oem_model_number,
                last_error,
            )
            continue
        _LOGGER.info(
            "AI task classified model %s into %d entities",
            device.oem_model_number,
            len(mapping.get("entities", [])),
        )
        return mapping, dropped
    raise LLMClassificationError(f"could not classify {device.oem_model_number}: {last_error}")
