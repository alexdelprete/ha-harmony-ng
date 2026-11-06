"""Tests for the buttons."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.pyharmonyng import CommandAction, HarmonyNgApiError, Snapshot
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


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
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


async def test_activity_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    watch_tv = "button.living_room_hub_start_watch_tv"
    assert hass.states.get(watch_tv).attributes["friendly_name"] == "Living Room Hub Start Watch TV"
    assert hass.states.get("button.living_room_hub_start_listen_to_music") is not None
    await press(hass, watch_tv)
    assert fake_transport.commands()[-1] == ("start_activity", ("123456",))

    coordinator = init_integration.runtime_data.coordinator
    only_first = coordinator.data.activities[:1]
    coordinator.async_set_updated_data(replace(coordinator.data, activities=only_first))
    await hass.async_block_till_done()
    assert hass.states.get(watch_tv).state != STATE_UNAVAILABLE
    assert (
        hass.states.get("button.living_room_hub_start_listen_to_music").state == STATE_UNAVAILABLE
    )


async def test_device_command_buttons(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_transport: FakeTransport,
    entity_registry: er.EntityRegistry,
) -> None:
    volume_up = "button.living_room_hub_lg_oled_tv_volumeup"
    entry = entity_registry.async_get(volume_up)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    commands = [
        e
        for e in er.async_entries_for_config_entry(entity_registry, init_integration.entry_id)
        if e.unique_id.endswith(("_command_PowerToggle", "_command_Menu", "_command_PowerOff"))
    ]
    assert len(commands) == 3

    entity_registry.async_update_entity(volume_up, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()
    await press(hass, volume_up)
    assert fake_transport.commands()[-1] == (
        "send_command",
        ("70321456", "VolumeUp", CommandAction.TAP, 1),
    )

    coordinator = init_integration.runtime_data.coordinator
    inventory = coordinator.data.inventory
    without_tv = replace(inventory, devices=inventory.devices[1:])
    coordinator.async_set_updated_data(replace(coordinator.data, inventory=without_tv))
    await hass.async_block_till_done()
    assert hass.states.get(volume_up).state == STATE_UNAVAILABLE
