"""Tests for the buttons."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.pyharmonyng import HarmonyNgApiError, Snapshot
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_json


@pytest.fixture(autouse=True)
def only_button() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.BUTTON]):
        yield


async def press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def test_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_presses(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    await press(hass, "button.living_room_hub_power_off")
    await press(hass, "button.living_room_hub_sync_remotes")
    await press(hass, "button.living_room_hub_cancel_activity")
    await press(hass, "button.harmony_ultimate_wake")
    await press(hass, "button.harmony_ultimate_sleep")
    assert fake_transport.commands() == [
        ("power_off", ()),
        ("push_config", ()),
        ("cancel_activity", ()),
        ("rf_wake", (1,)),
        ("rf_sleep", (1,)),
    ]
    fake_transport.errors["rf_wake"] = HarmonyNgApiError("already waking", code=202)
    with pytest.raises(HomeAssistantError, match="already waking"):
        await press(hass, "button.harmony_ultimate_wake")


async def test_wake_needs_capability(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    data = load_json("snapshot")
    data["hub"]["capabilities"].remove("rf_wake")
    fake_transport.snapshot = Snapshot.from_json(data)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("button.harmony_ultimate_wake").state == STATE_UNAVAILABLE
    assert hass.states.get("button.harmony_ultimate_sleep").state != STATE_UNAVAILABLE
