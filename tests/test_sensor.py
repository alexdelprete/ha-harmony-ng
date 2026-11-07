"""Tests for the sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.pyharmonyng import Snapshot
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_frames, load_json


@pytest.fixture(autouse=True)
def only_sensor() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.SENSOR]):
        yield


@pytest.mark.freeze_time("2026-11-06T12:00:00+00:00")
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_uptime_and_firmware(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    data = load_json("snapshot")
    data["hub"]["version"] = ""
    del data["hub"]["uptime_sec"]
    fake_transport.snapshot = Snapshot.from_json(data)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.living_room_hub_firmware").state == "unknown"
    registry = er.async_get(hass)
    registry.async_update_entity("sensor.living_room_hub_last_boot", disabled_by=None)
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.living_room_hub_last_boot").state == "unknown"


async def test_second_remote_appears(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    assert hass.states.get("sensor.harmony_elite_battery") is None
    frame = load_frames("ws_rf_status")[0]
    frame["slots"][1] = {
        "slot": 2,
        "active": True,
        "remote_id": "20141001120000-000003",
        "model": "elite",
        "model_name": "Harmony Elite",
        "skin": 111,
        "equad_id": 16417,
        "battery": {"percent": 55, "charging": True, "voltage_mv": 3700},
        "in_sync": False,
    }
    fake_transport.push(frame)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.harmony_elite_battery").state == "55"


async def test_battery_before_first_report(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The Hub's 0 % at 0 mV before a remote reports is shown as unknown, not as empty."""
    frame = load_frames("ws_rf_status")[0]
    frame["slots"][0]["battery"] = {"percent": 0, "charging": False, "voltage_mv": 0}
    fake_transport.push(frame)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.harmony_ultimate_battery").state == "unknown"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_last_boot_does_not_creep(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_transport: FakeTransport,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Computed once per snapshot from the uptime; later events do not move it."""
    before = hass.states.get("sensor.living_room_hub_last_boot").state
    freezer.tick(timedelta(minutes=10))
    fake_transport.push(load_frames("ws_rf_status")[0])
    await hass.async_block_till_done()
    assert hass.states.get("sensor.living_room_hub_last_boot").state == before


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_last_boot_from_boot_time(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    data = load_json("snapshot")
    data["hub"]["boot_time"] = 1793936234
    fake_transport.snapshot = Snapshot.from_json(data)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.living_room_hub_last_boot").state == datetime.fromtimestamp(
        1793936234, tz=UTC
    ).isoformat(timespec="seconds")


async def test_battery_report_time(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    entity = "sensor.harmony_ultimate_last_battery_report"
    assert hass.states.get(entity).state == "unknown"
    frame = load_frames("ws_rf_status")[0]
    frame["slots"][0]["battery"]["reported_at"] = 1794000000
    fake_transport.push(frame)
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == "2026-11-06T21:20:00+00:00"
    # Never reported: the Hub's placeholder is unknown, whatever its numbers say
    frame["slots"][0]["battery"] = {"percent": 0, "voltage_mv": 0, "reported_at": None}
    fake_transport.push(frame)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.harmony_ultimate_battery").state == "unknown"
    assert hass.states.get(entity).state == "unknown"
