"""Tests for the infrared emitters."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from infrared_protocols.commands.nec import NECCommand
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.pyharmonyng import HarmonyNgConnectionError, Snapshot
from homeassistant.components.infrared.helpers import async_send_command
from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_frames, load_json

FRONT = "infrared.living_room_hub_front_blaster"


@pytest.fixture(autouse=True)
def only_infrared() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.INFRARED]):
        yield


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_jacks_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    assert entity_registry.async_get("infrared.living_room_hub_emitter_jack_1").disabled
    assert entity_registry.async_get("infrared.living_room_hub_emitter_jack_2").disabled
    assert not entity_registry.async_get(FRONT).disabled


async def test_send(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    command = NECCommand(address=0x04, command=0x08, repeat_count=2)
    await async_send_command(hass, FRONT, command)
    name, (frequency, timings, port, repeats) = fake_transport.commands()[0]
    assert name == "ir_raw"
    assert frequency == 38000
    assert timings == command.get_raw_timings()
    assert port == 1
    assert repeats == 2
    assert hass.states.get(FRONT).state != "unknown"

    fake_transport.errors["ir_raw"] = HarmonyNgConnectionError("dropped")
    with pytest.raises(HomeAssistantError, match="Cannot reach the Hub"):
        await async_send_command(hass, FRONT, NECCommand(address=1, command=2))


async def test_needs_capability(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    data = load_json("snapshot")
    data["hub"]["capabilities"].remove("ir_raw")
    fake_transport.snapshot = Snapshot.from_json(data)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(FRONT).state == STATE_UNAVAILABLE


RECEIVER = "infrared.living_room_hub_receiver"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    fake_transport.snapshot = Snapshot.from_json(data)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(RECEIVER).state == "unknown"
    assert fake_transport.commands() == [("ir_capture", (True,))]

    received: list[Any] = []
    entity = hass.data["entity_components"]["infrared"].get_entity(RECEIVER)
    entity.async_subscribe_received_signal(received.append)
    fake_transport.push_frames("ws_ir_received")
    await hass.async_block_till_done()
    assert hass.states.get(RECEIVER).state != "unknown"
    assert received[0].modulation == 38000
    assert received[0].timings == [9000, -4500, 560, -560, 560, -1690, 560, -39000]

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert fake_transport.commands()[-1] == ("ir_capture", (False,))


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_without_capability(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    assert hass.states.get(RECEIVER).state == STATE_UNAVAILABLE
    assert ("ir_capture", (True,)) not in fake_transport.commands()


async def test_receiver_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    assert entity_registry.async_get(RECEIVER).disabled


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_capture_error_is_logged(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_transport: FakeTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    fake_transport.snapshot = Snapshot.from_json(data)
    fake_transport.errors["ir_capture"] = HarmonyNgConnectionError("dropped")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert "Could not start infrared capture" in caplog.text


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_capture_retried(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_transport: FakeTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request lost right after the Hub came back is tried again, logged once."""
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    data["hub"]["ir_capture"] = False
    fake_transport.snapshot = Snapshot.from_json(data)
    fake_transport.errors["ir_capture"] = HarmonyNgConnectionError("no reply from the Hub")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    def enables() -> int:
        return fake_transport.commands().count(("ir_capture", (True,)))

    assert enables() == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert enables() == 2
    assert caplog.text.count("Could not start infrared capture") == 1

    del fake_transport.errors["ir_capture"]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=62))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert enables() == 3
    assert "Infrared capture started" in caplog.text

    # Started: no more retries
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert enables() == 3


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_no_retry_once_hub_reports_on(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The request ran but its reply was lost: the Hub's status says on, no retry."""
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    fake_transport.snapshot = Snapshot.from_json(data)
    fake_transport.errors["ir_capture"] = HarmonyNgConnectionError("no reply from the Hub")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    on, _off = load_frames("firmware/ws_ir_capture")
    fake_transport.push(on)
    await hass.async_block_till_done(wait_background_tasks=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_transport.commands().count(("ir_capture", (True,))) == 1


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_retry_waits_for_hub(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """A retry due while the Hub is away is left to the Hub coming back."""
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    fake_transport.snapshot = Snapshot.from_json(data)
    fake_transport.errors["ir_capture"] = HarmonyNgConnectionError("no reply from the Hub")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    fake_transport.drop()
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_transport.commands().count(("ir_capture", (True,))) == 1


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_retry_cancelled_on_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    fake_transport.snapshot = Snapshot.from_json(data)
    fake_transport.errors["ir_capture"] = HarmonyNgConnectionError("no reply from the Hub")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_transport.commands().count(("ir_capture", (True,))) == 1


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_capture_back_on_after_restart(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The Hub boots with capture off: the receiver turns it on again."""
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    data["hub"]["ir_capture"] = True
    fake_transport.snapshot = Snapshot.from_json(data)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    def enables() -> int:
        return fake_transport.commands().count(("ir_capture", (True,)))

    assert enables() == 1
    # Events carry the same status along: no new request
    fake_transport.push_frames("ws_ir_received")
    fake_transport.push(load_frames("ws_rf_status")[0])
    await hass.async_block_till_done(wait_background_tasks=True)
    assert enables() == 1

    # The Hub restarted: back with capture off
    fake_transport.drop()
    await hass.async_block_till_done()
    assert hass.states.get(RECEIVER).state == STATE_UNAVAILABLE
    restarted = load_json("snapshot")
    restarted["hub"]["capabilities"].append("ir_capture")
    restarted["hub"]["ir_capture"] = False
    fake_transport.restore(Snapshot.from_json(restarted))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert enables() == 2

    # A new status that says off, while connected (e.g. republished over MQTT)
    fake_transport.restore(Snapshot.from_json(restarted))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert enables() == 3


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_receiver_follows_capture_event(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The Hub announces a change of the mode: off while enabled turns it on again."""
    data = load_json("snapshot")
    data["hub"]["capabilities"].append("ir_capture")
    fake_transport.snapshot = Snapshot.from_json(data)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = mock_config_entry.runtime_data.coordinator

    def enables() -> int:
        return fake_transport.commands().count(("ir_capture", (True,)))

    assert enables() == 1
    on, off = load_frames("firmware/ws_ir_capture")
    fake_transport.push(on)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data.hub.ir_capture is True
    assert enables() == 1

    # Switched off elsewhere (the web UI): the receiver wants it on
    fake_transport.push(off)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data.hub.ir_capture is False
    assert enables() == 2

    fake_transport.push({**on, "ir_capture_error": "stalled"})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data.hub.ir_capture_error == "stalled"
    assert enables() == 2
