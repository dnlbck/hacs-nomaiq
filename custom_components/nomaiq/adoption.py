"""Adoption of unknown devices: mapping resolution, dump sensors, Repairs offers.

The AdoptionManager decides which devices are mapping-managed (unknown models,
plus natively-supported models listed in the force_llm_models debug option),
resolves their mappings into `resolved` for the platforms, and maintains one
fixable Repairs issue per model that has no usable mapping yet. Triage is
deterministic (property metadata only) — the only AI call happens inside the
repairs fix flow when the user explicitly adopts a device.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import ayla_iot_unofficial.device
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import llm_client
from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_ENABLE_PROPERTY_DUMP,
    CONF_FORCE_LLM_MODELS,
    CONF_OFFER_ADOPTION,
    DEFAULT_ENABLE_PROPERTY_DUMP,
    DEFAULT_OFFER_ADOPTION,
    DOMAIN,
    ISSUE_ADOPT_PREFIX,
    ISSUE_TRANSLATION_KEY_ADOPT,
    MAX_DUMP_SENSORS_PER_DEVICE,
    NATIVE_MODELS,
    SIGNAL_NEW_MAPPED_ENTITIES,
    parse_force_models,
)
from .mappings import resolve
from .mappings.schema import EntityMapping, MappingsRootDict, ResolvedMapping
from .mappings.store import MappingsStore

if TYPE_CHECKING:
    from . import NomaIQConfigEntry
    from .coordinator import NomaIQDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class AdoptionManager:
    """Tracks mapping resolution and adoption offers for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NomaIQConfigEntry,
        coordinator: NomaIQDataUpdateCoordinator,
        store: MappingsStore,
        bundled: MappingsRootDict,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.store = store
        self.bundled = bundled

        options = entry.options
        self.ai_task_entity_id: str | None = options.get(CONF_AI_TASK_ENTITY_ID) or None
        self.offers_enabled: bool = bool(options.get(CONF_OFFER_ADOPTION, DEFAULT_OFFER_ADOPTION))
        self.dump_enabled: bool = bool(
            options.get(CONF_ENABLE_PROPERTY_DUMP, DEFAULT_ENABLE_PROPERTY_DUMP)
        )
        self.force_models: frozenset[str] = parse_force_models(options.get(CONF_FORCE_LLM_MODELS))

        # Serial -> resolved mapping; platforms only see devices listed here.
        self.resolved: dict[str, ResolvedMapping] = {}
        self._known_serials: set[str] = set()
        self._models_inflight: set[str] = set()  # repairs-flow concurrency lock

    # ---- predicates -------------------------------------------------------

    def is_forced(self, model: str | None) -> bool:
        """Return True if this natively-supported model is forced to the mapping path."""
        return bool(model) and model.casefold() in self.force_models

    def is_llm_managed(self, device: ayla_iot_unofficial.device.Device) -> bool:
        """Return True if this device goes through the mapping path."""
        model = device.oem_model_number
        return model not in NATIVE_MODELS or self.is_forced(model)

    def _model_needs_adoption(self, device: ayla_iot_unofficial.device.Device) -> bool:
        """True when no stored/bundled mapping yields entities for this model."""
        bare = resolve(device.oem_model_number, device.properties_full, self.store, self.bundled)
        return not bare.entities

    # ---- deterministic triage ----------------------------------------------

    def triage(self, device: ayla_iot_unofficial.device.Device) -> dict[str, str]:
        """Property-metadata triage for the Repairs offer. No AI involved."""
        total = 0
        writable = 0
        for meta in device.properties_full.values():
            if isinstance(meta, dict) and meta.get("base_type") == "file":
                continue
            total += 1
            if isinstance(meta, dict) and not meta.get("read_only"):
                writable += 1
        return {"property_count": str(total), "writable_count": str(writable)}

    # ---- repairs issue lifecycle --------------------------------------------

    def _issue_id(self, model: str) -> str:
        return f"{ISSUE_ADOPT_PREFIX}{self.entry.entry_id}_{model}"

    @callback
    def async_update_issues(self) -> None:
        """Create/delete one fixable adoption issue per model. Idempotent.

        The issue registry is the source of truth: issues survive config-entry
        reloads while this manager does not, so the diff must run against the
        registry, not instance state.
        """
        needed: dict[str, ayla_iot_unofficial.device.Device] = {}
        if self.offers_enabled:
            for device in self.coordinator.data or []:
                model = device.oem_model_number
                if model in needed:
                    continue
                if self.is_llm_managed(device) and self._model_needs_adoption(device):
                    needed[model] = device

        registry = ir.async_get(self.hass)
        prefix = f"{ISSUE_ADOPT_PREFIX}{self.entry.entry_id}_"
        existing: set[str] = {
            issue_id[len(prefix) :]
            for domain, issue_id in registry.issues
            if domain == DOMAIN and issue_id.startswith(prefix)
        }

        for model in existing - set(needed):
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(model))
        for model in set(needed) - existing:
            device = needed[model]
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id(model),
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_TRANSLATION_KEY_ADOPT,
                translation_placeholders={
                    "model": model,
                    "device_name": device.name,
                    **self.triage(device),
                },
                data={
                    "entry_id": self.entry.entry_id,
                    "oem_model": model,
                    "serial": device.serial_number,
                },
                learn_more_url="https://github.com/mnfjorge/hacs-nomaiq#adopting-unknown-devices",
            )

    # ---- resolution ---------------------------------------------------------

    def _claimed_properties(self, resolved: ResolvedMapping) -> set[str]:
        """All property names referenced by the mapping (expanded per fanout n)."""
        claimed: set[str] = set()
        ns = list(resolved.fanout.range) if resolved.fanout else []
        if resolved.fanout:
            for template in (
                resolved.fanout.gate_property,
                resolved.fanout.name_property,
            ):
                if template:
                    claimed.update(template.replace("{n}", str(n)) for n in ns)
        for spec in resolved.entities:
            for template in (spec.state_property, spec.command_property, spec.name_property):
                if not template:
                    continue
                if "{n}" in template:
                    claimed.update(template.replace("{n}", str(n)) for n in ns)
                else:
                    claimed.add(template)
        return claimed

    def _resolve_device(self, device: ayla_iot_unofficial.device.Device) -> ResolvedMapping:
        """Resolve the stored/bundled mapping and append dump sensors."""
        resolved = resolve(
            device.oem_model_number, device.properties_full, self.store, self.bundled
        )
        if self.dump_enabled:
            claimed = self._claimed_properties(resolved)
            count = 0
            for name in sorted(device.properties_full):
                if count >= MAX_DUMP_SENSORS_PER_DEVICE:
                    _LOGGER.warning(
                        "Device %s: property dump capped at %d sensors",
                        device.serial_number,
                        MAX_DUMP_SENSORS_PER_DEVICE,
                    )
                    break
                if name in claimed:
                    continue
                meta = device.properties_full.get(name)
                if isinstance(meta, dict) and meta.get("base_type") == "file":
                    continue
                resolved.entities.append(
                    EntityMapping(
                        kind="sensor",
                        id_suffix=f"prop_{name.lower()}",
                        state_property=name,
                        entity_category="diagnostic",
                        name_fallback=f"{{device_name}} {name}",
                    )
                )
                count += 1
        return resolved

    # ---- lifecycle ----------------------------------------------------------

    @callback
    def async_resolve_known(self) -> None:
        """Resolve all current devices; called once before platforms load."""
        for device in self.coordinator.data or []:
            self._known_serials.add(device.serial_number)
            if self.is_llm_managed(device):
                self.resolved[device.serial_number] = self._resolve_device(device)
        self.async_update_issues()

    @callback
    def _async_finalize(self, serial: str) -> None:
        """Publish a device's resolved mapping and signal the platforms."""
        device = self.coordinator.get_device(serial)
        if device is None or serial in self.resolved:
            return
        self.resolved[serial] = self._resolve_device(device)
        async_dispatcher_send(
            self.hass,
            SIGNAL_NEW_MAPPED_ENTITIES.format(entry_id=self.entry.entry_id),
            serial,
        )

    @callback
    def handle_coordinator_update(self) -> None:
        """Pick up devices that appear on the account after setup."""
        for device in self.coordinator.data or []:
            serial = device.serial_number
            if serial in self._known_serials:
                continue
            self._known_serials.add(serial)
            if not self.is_llm_managed(device):
                _LOGGER.info(
                    "New natively-supported device %s (%s) found; reload the "
                    "integration to add its entities",
                    device.name,
                    device.oem_model_number,
                )
                continue
            self._async_finalize(serial)
        self.async_update_issues()

    # ---- repairs-flow concurrency lock ---------------------------------------

    @callback
    def try_acquire_model(self, model: str) -> bool:
        """Reserve a model for one classification run; False if already running."""
        if model in self._models_inflight:
            return False
        self._models_inflight.add(model)
        return True

    @callback
    def release_model(self, model: str) -> None:
        self._models_inflight.discard(model)

    # ---- adoption ------------------------------------------------------------

    async def async_propose_mapping(
        self,
        device: ayla_iot_unofficial.device.Device,
        entity_id: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Run the AI task; return the proposed mapping plus validation drop reasons."""
        entity_id = entity_id or self.ai_task_entity_id
        if not entity_id:
            raise llm_client.LLMClassificationError(
                "no AI Task entity configured for NomaIQ (set one in the integration's options)"
            )
        mapping, dropped = await llm_client.async_classify_device(self.hass, device, entity_id)
        return dict(mapping), dropped

    async def async_apply_mapping(self, model: str, mapping: dict[str, Any]) -> None:
        """Persist an approved mapping; caller schedules the entry reload."""
        await self.store.set_mapping(model, mapping)  # type: ignore[arg-type]
