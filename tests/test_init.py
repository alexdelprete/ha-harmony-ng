"""Tests for Harmony NG integration setup."""

from __future__ import annotations

from pytest_homeassistant.common import MockConfigEntry

from custom_components.harmony_ng.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """Set up the integration from a config entry, then unload it."""
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "192.0.2.1"}, title="Test device")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
