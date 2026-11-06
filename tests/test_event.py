"""Tests for the remote button event entity."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_frames

ENTITY = "event.harmony_ultimate_1_button"


@pytest.fixture(autouse=True)
def only_event() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.EVENT]):
        yield


async def test_entity(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_press_and_release(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    press, release = load_frames("ws_button")
    fake_transport.push(press)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes["event_type"] == "press"
    assert state.attributes["button"] == "VolumeUp"
    assert state.attributes["device_id"] == "70321456"
    assert state.attributes["command"] == "VolumeUp"
    assert state.attributes["source"] == "elite_rf"

    fake_transport.push(release)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["event_type"] == "release"

    fake_transport.push({**press, "action": "hold", "seq": 99})
    other_slot = {**press, "slot": 2, "seq": 100}
    fake_transport.push(other_slot)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["event_type"] == "release"
