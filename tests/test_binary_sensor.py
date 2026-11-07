"""Tests for the binary sensors."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.const import DOMAIN
from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import HUB_ID, FakeTransport
from .pyharmonyng.conftest import load_frames, load_json

BUSY = "binary_sensor.living_room_hub_busy"
SYNC = "binary_sensor.harmony_ultimate_configuration_out_of_sync"
APPLE_TV = "binary_sensor.living_room_hub_apple_tv_connected"
SHIELD = "binary_sensor.living_room_hub_shield_connected"


@pytest.fixture(autouse=True)
def only_binary_sensor() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.BINARY_SENSOR]):
        yield


async def test_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_busy_and_sync(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    assert hass.states.get(BUSY).state == "off"
    assert hass.states.get(SYNC).state == "off"
    fake_transport.push(load_frames("ws_activity_switch")[0])
    rf = load_frames("ws_rf_status")[0]
    rf["slots"][0]["in_sync"] = False
    fake_transport.push(rf)
    await hass.async_block_till_done()
    assert hass.states.get(BUSY).state == "on"
    assert hass.states.get(SYNC).state == "on"
    del rf["slots"][0]["in_sync"]
    fake_transport.push(rf)
    await hass.async_block_till_done()
    assert hass.states.get(SYNC).state == "unknown"


async def test_bluetooth_hosts(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    apple = hass.states.get(APPLE_TV)
    assert apple.state == "on"
    assert apple.attributes["bdaddr"] == "AA:BB:CC:DD:EE:FF"
    assert hass.states.get(SHIELD).state == "off"

    bt = load_frames("ws_bt_status")[0]
    bt["target"] = "11:22:33:44:55:66"
    bt["hosts"] = [
        {"addr": "11:22:33:44:55:66", "name": "Shield", "connected": True},
        {"addr": "77:88:99:AA:BB:CC", "name": "Projector", "connected": False},
        {"addr": "", "name": "Not yet paired", "connected": False},
    ]
    fake_transport.push(bt)
    await hass.async_block_till_done()
    assert hass.states.get(APPLE_TV).state == STATE_UNAVAILABLE
    assert hass.states.get(SHIELD).state == "on"
    assert hass.states.get("binary_sensor.living_room_hub_projector_connected").state == "off"


@pytest.mark.usefixtures("fake_transport")
async def test_addressless_host_sensor_removed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """0.1.1 read a key the Hub does not send and left one sensor with an empty address."""
    mock_config_entry.add_to_hass(hass)
    stale = entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{HUB_ID}_bt_host_",
        config_entry=mock_config_entry,
        suggested_object_id="living_room_hub_tv_connected",
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get(stale.entity_id) is None
    assert hass.states.get(APPLE_TV).state == "on"


async def test_bluetooth_hosts_from_daemon_file(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The Hub forwards the daemon's file, which has a flag per host and none at the top."""
    fake_transport.push({"type": "bt_status", "seq": 99, **load_json("bt_status_daemon")})
    await hass.async_block_till_done()
    assert hass.states.get(APPLE_TV).state == "off"
    assert hass.states.get(SHIELD).state == "on"
