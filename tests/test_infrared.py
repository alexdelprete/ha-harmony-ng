"""Tests for the infrared emitters."""

from __future__ import annotations

from unittest.mock import patch

from infrared_protocols.commands.nec import NECCommand
import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.pyharmonyng import HarmonyNgConnectionError, Snapshot
from homeassistant.components.infrared.helpers import async_send_command
from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_json

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
