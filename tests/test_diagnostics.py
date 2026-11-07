"""Tests for the diagnostics."""

from __future__ import annotations

from pytest_homeassistant.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.harmony_ng.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant


async def test_diagnostics(
    hass: HomeAssistant, init_integration: MockConfigEntry, snapshot: SnapshotAssertion
) -> None:
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    assert result["entry"]["data"]["host"] == "**REDACTED**"
    assert result["state"]["bt"]["target"] == "**REDACTED**"
    assert result["state"]["bt"]["hosts"][0]["bdaddr"] == "**REDACTED**"
    assert result == snapshot(
        exclude=props("created_at", "modified_at", "entry_id", "received_at", "booted_at")
    )
