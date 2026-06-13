"""Persistent store for LLM-generated mappings, user promotions, and LLM
negative-cache entries.

Wraps homeassistant.helpers.storage.Store. One store per HA install (not per
config entry) since mappings are keyed by oem_model_number, which is global.
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import LLM_NEGATIVE_CACHE_SECONDS, STORAGE_KEY, STORAGE_VERSION
from .schema import ModelMappingDict


class PromotionEntry(TypedDict, total=False):
    kind: str
    command_property: str
    on_value: Any
    off_value: Any


class LLMAttemptEntry(TypedDict):
    tried_at: float
    result: str


class StoreData(TypedDict, total=False):
    mappings: dict[str, ModelMappingDict]
    promotions: dict[str, dict[str, PromotionEntry]]
    llm_attempts: dict[str, LLMAttemptEntry]


class MappingsStore:
    """Async wrapper around Store with typed accessors."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[StoreData] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: StoreData = {}
        self._loaded = False

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        self._data = raw or {}
        self._data.setdefault("mappings", {})
        self._data.setdefault("promotions", {})
        self._data.setdefault("llm_attempts", {})
        self._loaded = True

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    def get_mapping(self, oem_model: str) -> ModelMappingDict | None:
        return self._data.get("mappings", {}).get(oem_model)

    async def set_mapping(self, oem_model: str, mapping: ModelMappingDict) -> None:
        self._data.setdefault("mappings", {})[oem_model] = mapping
        await self.async_save()

    async def delete_mapping(self, oem_model: str) -> None:
        self._data.get("mappings", {}).pop(oem_model, None)
        self._data.get("llm_attempts", {}).pop(oem_model, None)
        await self.async_save()

    def get_promotions(self, oem_model: str) -> dict[str, PromotionEntry]:
        return self._data.get("promotions", {}).get(oem_model, {})

    async def add_promotion(
        self, oem_model: str, property_name: str, promotion: PromotionEntry
    ) -> None:
        promotions = self._data.setdefault("promotions", {}).setdefault(oem_model, {})
        promotions[property_name] = promotion
        await self.async_save()

    async def record_llm_attempt(self, oem_model: str, result: str) -> None:
        self._data.setdefault("llm_attempts", {})[oem_model] = {
            "tried_at": time.time(),
            "result": result,
        }
        await self.async_save()

    def should_skip_llm(self, oem_model: str) -> bool:
        attempt = self._data.get("llm_attempts", {}).get(oem_model)
        if attempt is None:
            return False
        if attempt.get("result") == "ok":
            return False
        return (time.time() - attempt.get("tried_at", 0)) < LLM_NEGATIVE_CACHE_SECONDS
