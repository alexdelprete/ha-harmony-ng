"""Tests for the coordinator: events, connection loss, refetches, identity migration."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.harmony_ng.const import DOMAIN
from custom_components.harmony_ng.coordinator import HarmonyNgCoordinator
from custom_components.harmony_ng.pyharmonyng import Snapshot
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import HUB_ID, REMOTE_ID, FakeTransport
from .pyharmonyng.conftest import load_frames, load_json

ACTIVITY_STATE = "sensor.living_room_hub_activity_state"
BATTERY = "sensor.harmony_ultimate_1_battery"


def fetch_count(transport: FakeTransport) -> int:
    return sum(1 for name, _ in transport.calls if name == "fetch_inventory")


async def test_events_update_state(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    assert hass.states.get(ACTIVITY_STATE).state == "idle"
    frames = load_frames("ws_activity_switch")
    fake_transport.push(frames[0])
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVITY_STATE).state == "starting"
    remote = hass.states.get("remote.living_room_hub")
    assert remote.state == "on"
    assert remote.attributes["activity_starting"] is True
    assert remote.attributes["current_activity"] == "Watch TV"

    for frame in frames[1:]:
        fake_transport.push(frame)
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVITY_STATE).state == "idle"
    remote = hass.states.get("remote.living_room_hub")
    assert remote.state == "off"
    assert remote.attributes["last_activity"] == "Watch TV"
    assert remote.attributes["activity_starting"] is False


async def test_connection_loss_and_recovery(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fetches = fetch_count(fake_transport)
    fake_transport.drop()
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVITY_STATE).state == STATE_UNAVAILABLE
    assert hass.states.get(BATTERY).state == STATE_UNAVAILABLE

    fake_transport.restore()
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVITY_STATE).state == "idle"
    assert hass.states.get(BATTERY).state == "87"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert fetch_count(fake_transport) == fetches


async def test_gap_triggers_refetch(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fetches = fetch_count(fake_transport)
    fake_transport.drop()
    fake_transport.restore(gap=True)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert fetch_count(fake_transport) == fetches + 1


async def test_config_change_triggers_refetch(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fetches = fetch_count(fake_transport)
    fake_transport.push({"type": "config_changed", "files": ["settings"], "seq": 90, "ts": 1})
    fake_transport.push({"type": "config_changed", "files": ["devices"], "seq": 91, "ts": 1})
    fake_transport.push({"type": "config_changed", "files": ["activities"], "seq": 92, "ts": 1})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert fetch_count(fake_transport) == fetches + 1


async def test_snapshot_with_changed_files_refetches(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fetches = fetch_count(fake_transport)
    changed = load_json("snapshot")
    changed["config"]["files"]["devices"] += 100
    fake_transport.drop()
    fake_transport.restore(Snapshot.from_json(changed))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert fetch_count(fake_transport) == fetches + 1


async def test_rf_and_bt_events(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    frame = load_frames("ws_rf_status")[0]
    frame["slots"][0]["battery"]["percent"] = 42
    frame["slots"][0]["battery"]["charging"] = True
    fake_transport.push(frame)
    bt = load_frames("ws_bt_status")[0]
    bt["connected"] = False
    fake_transport.push(bt)
    await hass.async_block_till_done()
    assert hass.states.get(BATTERY).state == "42"
    assert hass.states.get("binary_sensor.harmony_ultimate_1_charging").state == "on"
    assert hass.states.get("binary_sensor.living_room_hub_apple_tv_connected").state == "off"


async def test_remote_identity_migration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    without_id = load_json("snapshot")
    del without_id["rf_status"]["slots"][0]["remote_id"]
    fake_transport.snapshot = Snapshot.from_json(without_id)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    fallback = f"{HUB_ID}:slot1"
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, fallback), mock_config_entry.entry_id
    )
    assert device is not None
    battery = entity_registry.async_get(BATTERY)
    assert battery is not None
    assert battery.unique_id == f"{fallback}_battery"

    fake_transport.snapshot = Snapshot.from_json(load_json("snapshot"))
    fake_transport.push(load_frames("ws_rf_status")[0])
    await hass.async_block_till_done()

    migrated = device_registry.async_get(device.id)
    assert migrated is not None
    assert migrated.identifiers == {(DOMAIN, REMOTE_ID)}
    assert migrated.serial_number == REMOTE_ID
    battery = entity_registry.async_get(BATTERY)
    assert battery is not None
    assert battery.unique_id == f"{REMOTE_ID}_battery"
    assert hass.states.get(BATTERY).state == "87"
    # The same event again migrates nothing and reloads nothing.
    calls = len(fake_transport.calls)
    fake_transport.push(load_frames("ws_rf_status")[0])
    await hass.async_block_till_done()
    assert len(fake_transport.calls) == calls


async def test_hub_id_requires_unique_id(
    hass: HomeAssistant, fake_transport: FakeTransport
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    coordinator = HarmonyNgCoordinator(hass, entry, fake_transport)
    with pytest.raises(ValueError, match="unique id"):
        _ = coordinator.hub_id


async def test_events_before_setup_are_ignored(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    coordinator = HarmonyNgCoordinator(hass, mock_config_entry, fake_transport)
    fake_transport.push(load_frames("ws_button")[0])
    fake_transport.drop()
    assert coordinator.data is None
