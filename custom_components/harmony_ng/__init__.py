"""The Harmony NG integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, MANUFACTURER, MODEL, VERSION
from .coordinator import HarmonyNgCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


@dataclass
class HarmonyNgData:
    """Runtime data for the Harmony NG integration."""

    device_name: str
    coordinator: HarmonyNgCoordinator


type HarmonyNgConfigEntry = ConfigEntry[HarmonyNgData]


async def async_setup_entry(hass: HomeAssistant, entry: HarmonyNgConfigEntry) -> None:
    """Set up Harmony NG from a config entry.

    Returns None; failure is signalled by raising ConfigEntryNotReady,
    ConfigEntryAuthFailed or ConfigEntryError (Home Assistant 2026.11).
    """
    coordinator = HarmonyNgCoordinator(hass, entry)
    # Raises ConfigEntryNotReady when the device is unreachable (HA retries setup).
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = HarmonyNgData(device_name=entry.title, coordinator=coordinator)

    # Register the hub device. Entities find it again by identifier *and* entry id
    # (see entity.py): identifiers are only unique within a config entry.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, coordinator.device_unique_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title,
        sw_version=VERSION,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: HarmonyNgConfigEntry) -> None:
    """Unload a config entry, raising ConfigEntryError if a platform fails to unload."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
