"""Repairs platform: fix flow that adopts an unknown device via an AI task.

One fixable issue exists per unadopted model (created by AdoptionManager).
The flow: confirm (with inline AI Task picker when none is configured) →
visible progress while the AI task runs → preview of the proposed mapping →
apply (store + reload; issue auto-deleted) or discard (abort; issue stays).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from . import llm_client
from .const import CONF_AI_TASK_ENTITY_ID, MAX_PREVIEW_JSON_CHARS

_LOGGER = logging.getLogger(__name__)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the adoption flow for an unknown-device issue."""
    return AdoptDeviceRepairFlow(data or {})


class AdoptDeviceRepairFlow(RepairsFlow):
    """Guide the user through AI-adopting one unknown device model."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._entry_id: str = str(data.get("entry_id", ""))
        self._model: str = str(data.get("oem_model", ""))
        self._serial: str = str(data.get("serial", ""))
        self._entity_id: str | None = None
        self._picked_inline = False
        self._task: asyncio.Task | None = None
        self._mapping: dict[str, Any] | None = None
        self._dropped: list[str] = []
        self._error: str | None = None
        self._lock_held = False

    def _resolve_context(self):
        """Re-resolve (entry, manager, device) — never cache across steps.

        A reload mid-flow replaces runtime_data, so each step looks the
        context up fresh by entry_id.
        """
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return None, None, None
        coordinator = entry.runtime_data
        manager = coordinator.adoption
        device = coordinator.get_device(self._serial) or next(
            (d for d in coordinator.data or [] if d.oem_model_number == self._model),
            None,
        )
        return entry, manager, device

    def _release_lock(self) -> None:
        if not self._lock_held:
            return
        self._lock_held = False
        try:
            _, manager, _ = self._resolve_context()
            if manager is not None:
                manager.release_model(self._model)
        except Exception:
            _LOGGER.debug("Could not release adoption lock for %s", self._model)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Entry point; repairs passes the issue data as user_input here."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Confirm adoption; pick an AI Task entity inline when none is set."""
        entry, manager, device = self._resolve_context()
        if entry is None or manager is None:
            return self.async_abort(reason="entry_not_loaded")
        if device is None:
            return self.async_abort(reason="device_missing")

        configured = manager.ai_task_entity_id

        if user_input is not None:
            picked = user_input.get(CONF_AI_TASK_ENTITY_ID)
            if picked:
                self._entity_id = picked
                self._picked_inline = True
            else:
                self._entity_id = configured
            if not self._entity_id:
                return self.async_abort(reason="no_backend")
            return await self.async_step_classify()

        schema = vol.Schema({})
        if not configured:
            schema = vol.Schema(
                {
                    vol.Required(CONF_AI_TASK_ENTITY_ID): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="ai_task")
                    )
                }
            )
        triage = manager.triage(device)
        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            description_placeholders={
                "model": self._model,
                "device_name": device.name,
                **triage,
            },
        )

    async def async_step_classify(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Run the AI task with a visible progress step."""
        _, manager, device = self._resolve_context()
        if manager is None or device is None:
            self._release_lock()
            return self.async_abort(reason="entry_not_loaded")

        if self._task is None and self._mapping is None and self._error is None:
            if not manager.try_acquire_model(self._model):
                return self.async_abort(reason="classification_in_progress")
            self._lock_held = True
            self._task = self.hass.async_create_task(
                manager.async_propose_mapping(device, entity_id=self._entity_id),
                name=f"nomaiq_adopt_{self._model}",
            )

        if self._task is not None and not self._task.done():
            return self.async_show_progress(
                step_id="classify",
                progress_action="classifying",
                progress_task=self._task,
                description_placeholders={"model": self._model},
            )

        if self._task is not None:
            try:
                self._mapping, self._dropped = self._task.result()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self._error = str(err) or type(err).__name__
            finally:
                self._task = None
                self._release_lock()

        if self._error is not None:
            return self.async_show_progress_done(next_step_id="failed")
        return self.async_show_progress_done(next_step_id="preview")

    async def async_step_failed(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Offer retry or cancel after a failed classification."""
        return self.async_show_menu(
            step_id="failed",
            menu_options=["retry", "discard"],
            description_placeholders={
                "model": self._model,
                "error": self._error or "unknown error",
            },
        )

    async def async_step_retry(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Clear the failure and classify again."""
        self._error = None
        self._mapping = None
        self._dropped = []
        return await self.async_step_classify()

    async def async_step_preview(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show the proposed mapping for review."""
        if self._mapping is None:
            return self.async_abort(reason="entry_not_loaded")
        pretty = json.dumps(self._mapping, indent=2)
        if len(pretty) > MAX_PREVIEW_JSON_CHARS:
            pretty = pretty[:MAX_PREVIEW_JSON_CHARS] + "\n… (truncated)"
        dropped = ""
        if self._dropped:
            dropped = "\n\n**Dropped during validation:**\n" + "\n".join(
                f"- {reason}" for reason in self._dropped
            )
        return self.async_show_menu(
            step_id="preview",
            menu_options=["apply", "discard"],
            description_placeholders={
                "model": self._model,
                "summary": llm_client.summarize_mapping(self._mapping),
                "mapping_json": pretty,
                "dropped": dropped,
            },
        )

    async def async_step_apply(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Store the mapping and reload the entry; the issue auto-deletes."""
        entry, manager, _ = self._resolve_context()
        if entry is None or manager is None or self._mapping is None:
            return self.async_abort(reason="entry_not_loaded")

        await manager.async_apply_mapping(self._model, self._mapping)
        if self._picked_inline and self._entity_id:
            # Persisting the option fires the update listener, which reloads
            # the entry — the sole reload trigger on this path.
            self.hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_AI_TASK_ENTITY_ID: self._entity_id},
            )
        else:
            self.hass.async_create_task(self.hass.config_entries.async_reload(entry.entry_id))
        return self.async_create_entry(title="", data={})

    async def async_step_discard(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Abort without storing; the issue persists for a later adoption."""
        return self.async_abort(reason="discarded")

    @callback
    def async_remove(self) -> None:
        """Clean up when the dialog is abandoned."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._release_lock()
