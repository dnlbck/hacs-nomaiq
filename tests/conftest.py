"""Test setup: make the repo importable and stub homeassistant if absent.

The unit tests only exercise pure functions (schema validation, JSON
extraction, prompt building, mapping resolution). When the real homeassistant
package isn't installed (e.g. unsupported Python version), minimal stand-ins
for the few imported symbols are registered instead.
"""

from __future__ import annotations

import enum
import sys
import types
from pathlib import Path
from typing import Generic, TypeVar

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import homeassistant  # noqa: F401
except ImportError:
    T = TypeVar("T")

    def _module(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    ha = _module("homeassistant")

    core = _module("homeassistant.core")

    class HomeAssistant:  # noqa: D401
        pass

    class Context:
        pass

    class ServiceCall:
        pass

    def callback(func):
        return func

    core.HomeAssistant = HomeAssistant
    core.Context = Context
    core.ServiceCall = ServiceCall
    core.callback = callback

    exceptions = _module("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    class ConfigEntryNotReady(HomeAssistantError):
        pass

    class ServiceValidationError(HomeAssistantError):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    exceptions.ServiceValidationError = ServiceValidationError

    const = _module("homeassistant.const")

    class Platform(enum.StrEnum):
        BINARY_SENSOR = "binary_sensor"
        COVER = "cover"
        HUMIDIFIER = "humidifier"
        LIGHT = "light"
        NUMBER = "number"
        SELECT = "select"
        SENSOR = "sensor"
        SWITCH = "switch"

    const.Platform = Platform
    const.CONF_USERNAME = "username"
    const.CONF_PASSWORD = "password"
    const.PERCENTAGE = "%"

    config_entries = _module("homeassistant.config_entries")

    class ConfigEntry:
        def __class_getitem__(cls, _item):
            return cls

    class ConfigEntryState(enum.Enum):
        LOADED = "loaded"

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigEntryState = ConfigEntryState

    helpers = _module("homeassistant.helpers")

    aiohttp_client = _module("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None

    typing_mod = _module("homeassistant.helpers.typing")
    typing_mod.ConfigType = dict

    update_coordinator = _module("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator(Generic[T]):
        def __init__(self, hass, logger, name=None, update_interval=None, update_method=None):
            self.hass = hass
            self.logger = logger
            self.update_interval = update_interval

    class UpdateFailed(Exception):
        pass

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed

    storage = _module("homeassistant.helpers.storage")

    class Store(Generic[T]):
        def __init__(self, hass, version, key):
            self.version = version
            self.key = key

        async def async_load(self):
            return None

        async def async_save(self, data):
            pass

    storage.Store = Store

    issue_registry = _module("homeassistant.helpers.issue_registry")

    class IssueSeverity(enum.Enum):
        CRITICAL = "critical"
        ERROR = "error"
        WARNING = "warning"

    issue_registry.IssueSeverity = IssueSeverity
    issue_registry.async_create_issue = lambda *args, **kwargs: None
    issue_registry.async_delete_issue = lambda *args, **kwargs: None
    issue_registry.async_get = lambda hass: None

    ha.core = core
    ha.exceptions = exceptions
    ha.const = const
    ha.config_entries = config_entries
    ha.helpers = helpers
    helpers.aiohttp_client = aiohttp_client
    helpers.typing = typing_mod
    helpers.update_coordinator = update_coordinator
    helpers.storage = storage
