"""Remotes, Bluetooth hosts and configured devices follow the Hub without a reload.

Quality scale rules dynamic-devices and stale-devices: what the Hub adds appears on
the next update, what it no longer reports is removed with its device.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.harmony_ng.const import DOMAIN
from custom_components.harmony_ng.pyharmonyng import Inventory, Snapshot
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import HUB_ID, REMOTE_ID, FakeTransport
from .pyharmonyng.conftest import load_frames, load_json

ELITE_ID = "20180101120000-000003"
OLD_BATTERY = "sensor.harmony_ultimate_battery"
ELITE = {"model": "elite", "model_name": "Harmony Elite", "skin": 111, "equad_id": 0}
# Battery, voltage and last report; charging and sync; wake and sleep; the button event
ENTITIES_PER_REMOTE = 8


def rf_frame(slot1: dict[str, Any] | None = None, **status: Any) -> dict[str, Any]:
    """Return the Hub's RF status with slot 1 changed."""
    frame = load_frames("ws_rf_status")[0]
    frame.update(status)
    frame["slots"][0].update(slot1 or {})
    return frame


def remote_devices(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, dr.DeviceEntry]:
    """Return the entry's remote devices by identifier."""
    devices = {}
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        identifiers = {i for domain, i in device.identifiers if domain == DOMAIN}
        if identifiers and HUB_ID not in identifiers:
            devices[next(iter(identifiers))] = device
    return devices


def entity_count(hass: HomeAssistant, device: dr.DeviceEntry) -> int:
    """Return how many registry entries the device has."""
    return len(
        er.async_entries_for_device(er.async_get(hass), device.id, include_disabled_entities=True)
    )


async def test_remote_swapped_in_a_slot(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """Another remote in slot 1: its device at once, the old one removed."""
    assert set(remote_devices(hass, init_integration)) == {REMOTE_ID}
    calls = len(fake_transport.calls)

    fake_transport.push(rf_frame({"remote_id": ELITE_ID, **ELITE}))
    await hass.async_block_till_done()

    devices = remote_devices(hass, init_integration)
    assert set(devices) == {ELITE_ID}
    elite = devices[ELITE_ID]
    assert elite.model == "Harmony Elite"
    assert elite.serial_number == ELITE_ID
    assert entity_count(hass, elite) == ENTITIES_PER_REMOTE
    assert hass.states.get(OLD_BATTERY) is None
    assert hass.states.get("sensor.harmony_elite_battery").state == "87"
    # No reload: the transport was not connected again
    assert ("connect", ()) not in fake_transport.calls[calls:]


async def test_remote_unpaired_then_another_paired(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The order the Hub reports a re-pairing in: no unit id first, then the new one."""
    fake_transport.push(rf_frame({"remote_id": None, "model": "unknown", "model_name": None}))
    await hass.async_block_till_done()
    devices = remote_devices(hass, init_integration)
    fallback = f"{HUB_ID}:slot1"
    assert set(devices) == {fallback}
    assert entity_count(hass, devices[fallback]) == ENTITIES_PER_REMOTE

    # The unit id arrives: the slot's device is re-keyed and the entry reloads
    snapshot = load_json("snapshot")
    snapshot["rf_status"]["slots"][0].update({"remote_id": ELITE_ID, **ELITE})
    fake_transport.snapshot = Snapshot.from_json(snapshot)
    fake_transport.push(rf_frame({"remote_id": ELITE_ID, **ELITE}))
    await hass.async_block_till_done()

    devices = remote_devices(hass, init_integration)
    assert set(devices) == {ELITE_ID}
    assert entity_count(hass, devices[ELITE_ID]) == ENTITIES_PER_REMOTE
    assert hass.states.get("sensor.harmony_remote_battery").state == "87"


async def test_remote_unpaired_and_new_slot(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """A slot that empties loses its device; one that becomes active gets one."""
    frame = rf_frame({"active": False, "remote_id": None})
    assert frame["slots"][1]["slot"] == 2
    frame["slots"][1] = {
        **load_frames("ws_rf_status")[0]["slots"][0],
        "slot": 2,
        "remote_id": ELITE_ID,
        **ELITE,
    }
    fake_transport.push(frame)
    await hass.async_block_till_done()
    devices = remote_devices(hass, init_integration)
    assert set(devices) == {ELITE_ID}
    assert entity_count(hass, devices[ELITE_ID]) == ENTITIES_PER_REMOTE
    assert hass.states.get(OLD_BATTERY) is None


async def test_nothing_removed_while_rf_is_down(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """A report from a stopped RF service is not complete; the remote stays."""
    fake_transport.push(rf_frame({"active": False}, running=False))
    await hass.async_block_till_done()
    assert set(remote_devices(hass, init_integration)) == {REMOTE_ID}
    assert er.async_get(hass).async_get(OLD_BATTERY) is not None

    # Back with the same remote: the same entities, none added twice
    fake_transport.push(rf_frame())
    await hass.async_block_till_done()
    devices = remote_devices(hass, init_integration)
    assert entity_count(hass, devices[REMOTE_ID]) == ENTITIES_PER_REMOTE
    assert hass.states.get(OLD_BATTERY).state == "87"


async def test_removed_remote_comes_back(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """Paired again later: new entities, with the entity ids it had."""
    fake_transport.push(rf_frame({"active": False, "remote_id": None}))
    await hass.async_block_till_done()
    assert remote_devices(hass, init_integration) == {}
    assert hass.states.get(OLD_BATTERY) is None

    fake_transport.push(rf_frame())
    await hass.async_block_till_done()
    devices = remote_devices(hass, init_integration)
    assert entity_count(hass, devices[REMOTE_ID]) == ENTITIES_PER_REMOTE
    assert hass.states.get(OLD_BATTERY).state == "87"


async def test_bluetooth_hosts_follow_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """Hosts are kept while the Bluetooth daemon is down, removed once it drops them."""
    apple_tv = "binary_sensor.living_room_hub_apple_tv_connected"
    bt = load_frames("ws_bt_status")[0]
    fake_transport.push({**bt, "running": False, "hosts": []})
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(apple_tv) is not None

    hosts = [{"addr": "11:22:33:44:55:66", "name": "Shield", "connected": False}]
    fake_transport.push({**bt, "running": True, "hosts": hosts})
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(apple_tv) is None
    assert hass.states.get("binary_sensor.living_room_hub_shield_connected") is not None


async def test_removed_command_loses_its_button(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """A command the device no longer has: its button is removed, the others stay."""
    entity_registry = er.async_get(hass)
    device = fake_transport.inventory.devices[0]
    unique_id = f"{HUB_ID}:device:{device.id}_command_{{}}"
    dropped, kept = device.commands[0], device.commands[1]
    assert entity_registry.async_get_entity_id("button", DOMAIN, unique_id.format(dropped))

    fake_transport.inventory = Inventory(
        devices=(
            replace(device, commands=device.commands[1:]),
            *fake_transport.inventory.devices[1:],
        ),
        version=None,
    )
    fake_transport.push({"type": "config_changed", "files": ["devices"], "seq": 91, "ts": 1})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert entity_registry.async_get_entity_id("button", DOMAIN, unique_id.format(dropped)) is None
    assert entity_registry.async_get_entity_id("button", DOMAIN, unique_id.format(kept))


async def test_stale_registry_entries_removed_at_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """What the Hub dropped while Home Assistant was not running goes at the next start."""
    mock_config_entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    old_remote = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, ELITE_ID)},
        name="Harmony Elite",
    )
    old_battery = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{ELITE_ID}_battery",
        config_entry=mock_config_entry,
        device_id=old_remote.id,
    )
    old_host = entity_registry.async_get_or_create(
        "binary_sensor", DOMAIN, f"{HUB_ID}_bt_host_778899aabbcc", config_entry=mock_config_entry
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(old_remote.id) is None
    assert entity_registry.async_get(old_battery.entity_id) is None
    assert entity_registry.async_get(old_host.entity_id) is None
    assert set(remote_devices(hass, mock_config_entry)) == {REMOTE_ID}


async def test_nothing_changes_while_a_reload_is_pending(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """Remotes being re-keyed: the reload creates the entities, nothing is removed before."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator.reload_pending = True
    fake_transport.push(rf_frame({"remote_id": ELITE_ID, **ELITE}))
    await hass.async_block_till_done()
    assert set(remote_devices(hass, init_integration)) == {REMOTE_ID}
    assert er.async_get(hass).async_get(OLD_BATTERY) is not None


async def test_unit_id_that_arrived_while_stopped_keeps_the_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The slot's device is re-keyed at setup instead of being removed as stale."""
    mock_config_entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    fallback = f"{HUB_ID}:slot1"
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, fallback)},
        name="Harmony Ultimate",
    )
    battery = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{fallback}_battery",
        config_entry=mock_config_entry,
        device_id=device.id,
        suggested_object_id="harmony_ultimate_battery",
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    migrated = device_registry.async_get(device.id)
    assert migrated is not None
    assert migrated.identifiers == {(DOMAIN, REMOTE_ID)}
    kept = entity_registry.async_get(battery.entity_id)
    assert kept is not None
    assert kept.unique_id == f"{REMOTE_ID}_battery"
    assert hass.states.get(battery.entity_id).state == "87"
