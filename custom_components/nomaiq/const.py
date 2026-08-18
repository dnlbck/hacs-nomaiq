"""Constants for the nomaiq integration."""

from __future__ import annotations

DOMAIN = "nomaiq"
CLIENT_ID = "ctc-noma-Bg-id"
CLIENT_SECRET = "ctc-noma-WNHWBmAGLoaMl8xq8lx9XxGmiTQ"

# Update intervals
NORMAL_UPDATE_INTERVAL = 30  # seconds
TRANSITION_UPDATE_INTERVAL = 2  # seconds for devices opening/closing

# Models with hand-written entity support; everything else goes through the
# mapping/adoption path.
NATIVE_MODELS: frozenset[str] = frozenset({"gdo", "water-controller", "dehum"})

# Persistent mapping store (homeassistant.helpers.storage.Store)
STORAGE_KEY = "nomaiq_mappings"
STORAGE_VERSION = 1

# AI Task adoption
AI_TASK_TIMEOUT_SECONDS = 120
MAX_DUMP_SENSORS_PER_DEVICE = 64
MAX_PROMPT_PROPERTIES = 120
MAX_PREVIEW_JSON_CHARS = 3000

# Options keys
CONF_AI_TASK_ENTITY_ID = "ai_task_entity_id"
CONF_OFFER_ADOPTION = "offer_adoption"
CONF_ENABLE_PROPERTY_DUMP = "enable_property_dump"
CONF_FORCE_LLM_MODELS = "force_llm_models"
DEFAULT_OFFER_ADOPTION = True
DEFAULT_ENABLE_PROPERTY_DUMP = True

# Services
SERVICE_UNADOPT_DEVICE = "unadopt_device"
ATTR_OEM_MODEL = "oem_model"

# Repairs
ISSUE_ADOPT_PREFIX = "adopt_"
ISSUE_TRANSLATION_KEY_ADOPT = "adopt_device"

# Dispatcher signal for entities created after initial platform setup.
SIGNAL_NEW_MAPPED_ENTITIES = "nomaiq_new_mapped_entities_{entry_id}"


def parse_force_models(raw: str | None) -> frozenset[str]:
    """Parse the force_llm_models option ("water-controller, foo") into a set.

    Model comparison is case-insensitive; entries are casefolded here and the
    caller must casefold the model number before membership checks.
    """
    if not raw:
        return frozenset()
    return frozenset(part.strip().casefold() for part in raw.split(",") if part.strip())
