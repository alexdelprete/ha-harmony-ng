"""The Harmony NG integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_TOKEN, CONF_TRANSPORT, DEFAULT_PORT, DOMAIN, PLATFORMS, TRANSPORT_API
from .coordinator import HarmonyNgCoordinator
from .services import async_setup_services
from .transport import HarmonyNgTransport
from .transport.api import ApiTransport

_LOGGER = logging.getLogger(__name__)


@dataclass
class HarmonyNgData:
    """Runtime data of a config entry."""

    coordinator: HarmonyNgCoordinator


type HarmonyNgConfigEntry = ConfigEntry[HarmonyNgData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services; they exist whether or not a Hub is set up."""
    async_setup_services(hass)
    return True


def build_transport(hass: HomeAssistant, entry: ConfigEntry) -> HarmonyNgTransport:
    """Return the transport the entry is configured for."""
    transport = entry.data.get(CONF_TRANSPORT, TRANSPORT_API)
    if transport != TRANSPORT_API:
        raise NotImplementedError(f"transport {transport} arrives in a later milestone")
    return ApiTransport(
        entry.data[CONF_HOST],
        async_get_clientsession(hass),
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        token=entry.data.get(CONF_TOKEN),
    )


async def async_setup_entry(hass: HomeAssistant, entry: HarmonyNgConfigEntry) -> None:
    """Set up a Hub from a config entry.

    Returns None; failure is signalled by raising ConfigEntryNotReady or
    ConfigEntryAuthFailed from the coordinator's first refresh.
    """
    coordinator = HarmonyNgCoordinator(hass, entry, build_transport(hass, entry))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = HarmonyNgData(coordinator=coordinator)

    # The Hub device exists before any entity, so remotes can link to it by
    # registry id (via_device_id) and the coordinator can find it by identifier.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **coordinator.hub_device_info()
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: HarmonyNgConfigEntry) -> None:
    """Unload a config entry and close its transport."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
    await entry.runtime_data.coordinator.async_shutdown()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: HarmonyNgConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Let the user delete a remote that is no longer paired; never the Hub."""
    coordinator = entry.runtime_data.coordinator
    identifiers = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
    if coordinator.hub_id in identifiers:
        return False
    for rf_slot in coordinator.data.rf.active_slots:
        if coordinator.remote_identifier(rf_slot.slot) in identifiers:
            return False
    return True
