"""Diagnostics: the entry, the options and the last state, with secrets redacted."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from . import HarmonyNgConfigEntry
from .const import CONF_MQTT_BASE_TOPIC, CONF_TOKEN

TO_REDACT = {"host", CONF_TOKEN, CONF_MQTT_BASE_TOPIC, "target", "bdaddr", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HarmonyNgConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    state = coordinator.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "transport": coordinator.transport_name,
        "connected": coordinator.transport.connected,
        "capabilities": sorted(coordinator.transport.capabilities),
        "state": async_redact_data(_to_plain(state), TO_REDACT) if state is not None else None,
    }


def _to_plain(value: Any) -> Any:
    """Turn the state's dataclasses, sets and enums into JSON-friendly values."""
    if is_dataclass(value) and not isinstance(value, type):
        return _to_plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted(_to_plain(item) for item in value)
    if isinstance(value, list | tuple):
        return [_to_plain(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, str | int | float | bool):
        return value.value
    return value
