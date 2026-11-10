"""Device info follows what the Hub reports, without a reload."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.harmony_ng.const import DOMAIN
from custom_components.harmony_ng.pyharmonyng import Inventory, Snapshot
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .conftest import HUB_ID, REMOTE_ID, FakeTransport
from .pyharmonyng.conftest import load_frames, load_json


def device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> dr.DeviceEntry:
    """Return the entry's device with that identifier."""
    found = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id)
    assert found is not None
    return found


def child(hass: HomeAssistant, entry: MockConfigEntry, device_id: str) -> dr.ChildDeviceEntry:
    """Return the child device of a configured device."""
    found = dr.async_get(hass).async_get_child_device_by_identifier(
        (DOMAIN, f"{HUB_ID}:device:{device_id}"), entry.entry_id
    )
    assert found is not None
    return found


async def test_hub_firmware_update(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The Hub comes back with a new firmware: its device shows it at once."""
    hub = device(hass, init_integration, HUB_ID)
    assert hub.sw_version == "2.2.0"
    assert hub.hw_version is None
    data = load_json("snapshot")
    data["hub"].update({"version": "2.3.0", "firmware": "4.15.250"})
    fake_transport.restore(Snapshot.from_json(data))
    await hass.async_block_till_done()
    hub = device(hass, init_integration, HUB_ID)
    assert hub.sw_version == "2.3.0"
    assert hub.hw_version == "4.15.250"


async def test_remote_firmware_update(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """A remote updated over the air: its device shows the new version."""
    remote = device(hass, init_integration, REMOTE_ID)
    assert remote.sw_version == "2.2.0"
    frame = load_frames("ws_rf_status")[0]
    frame["slots"][0]["sw_version"] = "2.4.0"
    fake_transport.push(frame)
    await hass.async_block_till_done()
    remote = device(hass, init_integration, REMOTE_ID)
    assert remote.sw_version == "2.4.0"
    assert remote.serial_number == REMOTE_ID
    assert remote.model == "Harmony Ultimate"


async def test_unknown_values_leave_the_device_as_it_is(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """A version or product the Hub does not report does not blank the device."""
    frame = load_frames("ws_rf_status")[0]
    frame["slots"][0].update({"sw_version": None, "model": "unknown", "model_name": None})
    frame["slots"][0].pop("skin", None)
    frame["slots"][0].pop("equad_id", None)
    fake_transport.push(frame)
    await hass.async_block_till_done()
    remote = device(hass, init_integration, REMOTE_ID)
    assert remote.sw_version == "2.2.0"
    assert remote.model == "Harmony Ultimate"
    assert remote.name == "Harmony Ultimate"


async def test_configured_device_renamed_on_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The child device takes the new name; a name the user set stays in front."""
    configured = fake_transport.inventory.devices[0]
    first = child(hass, init_integration, configured.id)
    other = fake_transport.inventory.devices[1]
    other_child = child(hass, init_integration, other.id)
    dr.async_get(hass).async_update_child_device(other_child.id, name_by_user="Mine")

    fake_transport.inventory = Inventory(
        devices=(
            replace(configured, name="Living Room TV"),
            replace(other, name="Renamed"),
            *fake_transport.inventory.devices[2:],
        ),
        version=None,
    )
    fake_transport.push({"type": "config_changed", "files": ["devices"], "seq": 91, "ts": 1})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    renamed = registry.async_get(first.id)
    assert renamed is not None
    assert renamed.name == "Living Room TV"
    kept = registry.async_get(other_child.id)
    assert kept is not None
    assert kept.name == "Renamed"
    assert kept.name_by_user == "Mine"
