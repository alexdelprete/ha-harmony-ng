"""Tests for the remote entity."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.const import (
    CONF_DEFAULT_ACTIVITY,
    CONF_DELAY_SECS,
    DOMAIN,
    SERVICE_SYNC,
)
from custom_components.harmony_ng.pyharmonyng import (
    CommandAction,
    Device,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
    Inventory,
)
from homeassistant.components.remote import (
    ATTR_ACTIVITY,
    ATTR_COMMAND,
    ATTR_DELAY_SECS,
    ATTR_DEVICE,
    ATTR_HOLD_SECS,
    ATTR_NUM_REPEATS,
    DOMAIN as REMOTE_DOMAIN,
    SERVICE_SEND_COMMAND,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import HUB_ID, POWER_OFF_ACTIVITY, FakeTransport
from .pyharmonyng.conftest import load_frames

ENTITY = "remote.living_room_hub"


@pytest.fixture(autouse=True)
def only_remote() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.REMOTE]):
        yield


async def test_entity(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_turn_on_and_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    await hass.services.async_call(
        REMOTE_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY, ATTR_ACTIVITY: "Watch TV"},
        blocking=True,
    )
    await hass.services.async_call(
        REMOTE_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY, ATTR_ACTIVITY: "234567"},
        blocking=True,
    )
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert fake_transport.commands() == [
        ("start_activity", ("123456",)),
        ("start_activity", ("234567",)),
        ("power_off", ()),
    ]

    with pytest.raises(ServiceValidationError, match="No activity named"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: ENTITY, ATTR_ACTIVITY: "Nope"},
            blocking=True,
        )


async def test_turn_on_default_activity(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    with pytest.raises(ServiceValidationError, match="No activity given"):
        await hass.services.async_call(
            REMOTE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )

    for frame in load_frames("ws_activity_switch"):
        fake_transport.push(frame)
    await hass.async_block_till_done()
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert fake_transport.commands()[-1] == ("start_activity", ("123456",))

    hass.config_entries.async_update_entry(
        init_integration, options={CONF_DEFAULT_ACTIVITY: "Listen to Music"}
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert fake_transport.commands()[-1] == ("start_activity", ("234567",))


async def test_send_command(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    sleep = AsyncMock()
    with patch("custom_components.harmony_ng.remote.asyncio.sleep", sleep):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {
                ATTR_ENTITY_ID: ENTITY,
                ATTR_COMMAND: ["volumeup", "Mute"],
                ATTR_DEVICE: "LG OLED TV",
                ATTR_NUM_REPEATS: 2,
                ATTR_DELAY_SECS: 0.1,
            },
            blocking=True,
        )
    assert fake_transport.commands() == [
        ("send_command", ("70321456", "VolumeUp", CommandAction.TAP, 1)),
        ("send_command", ("70321456", "Mute", CommandAction.TAP, 1)),
        ("send_command", ("70321456", "VolumeUp", CommandAction.TAP, 1)),
        ("send_command", ("70321456", "Mute", CommandAction.TAP, 1)),
    ]
    assert [call.args[0] for call in sleep.call_args_list] == [0.1, 0.1, 0.1]


async def test_send_command_hold(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    hass.config_entries.async_update_entry(init_integration, options={CONF_DELAY_SECS: 0.3})
    await hass.async_block_till_done()
    sleep = AsyncMock()
    with patch("custom_components.harmony_ng.remote.asyncio.sleep", sleep):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {
                ATTR_ENTITY_ID: ENTITY,
                ATTR_COMMAND: ["VolumeUp", "VolumeDown"],
                ATTR_DEVICE: "70321456",
                ATTR_HOLD_SECS: 1.5,
            },
            blocking=True,
        )
    assert fake_transport.commands() == [
        ("send_command", ("70321456", "VolumeUp", CommandAction.PRESS, 1)),
        ("send_command", ("70321456", "VolumeUp", CommandAction.RELEASE, 1)),
        ("send_command", ("70321456", "VolumeDown", CommandAction.PRESS, 1)),
        ("send_command", ("70321456", "VolumeDown", CommandAction.RELEASE, 1)),
    ]
    assert [call.args[0] for call in sleep.call_args_list] == [1.5, 0.3, 1.5]


async def test_send_command_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    with pytest.raises(ServiceValidationError, match="device is required"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: ENTITY, ATTR_COMMAND: ["VolumeUp"]},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="No device named Nope"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: ENTITY, ATTR_COMMAND: ["VolumeUp"], ATTR_DEVICE: "Nope"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="has no command named Play"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: ENTITY, ATTR_COMMAND: ["Play"], ATTR_DEVICE: "LG OLED TV"},
            blocking=True,
        )
    assert fake_transport.commands() == []

    fake_transport.errors["send_command"] = HarmonyNgBusyError("Interlock busy")
    with pytest.raises(HomeAssistantError, match="busy"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: ENTITY, ATTR_COMMAND: ["VolumeUp"], ATTR_DEVICE: "LG OLED TV"},
            blocking=True,
        )
    fake_transport.errors["start_activity"] = HarmonyNgConnectionError("dropped")
    with pytest.raises(HomeAssistantError, match="Cannot reach the Hub"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: ENTITY, ATTR_ACTIVITY: "Watch TV"},
            blocking=True,
        )


async def test_sync_service(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    await hass.services.async_call(DOMAIN, SERVICE_SYNC, {ATTR_ENTITY_ID: ENTITY}, blocking=True)
    assert fake_transport.commands() == [("push_config", ())]


TV = "remote.living_room_hub_lg_oled_tv"


async def test_device_remotes(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_transport: FakeTransport,
    entity_registry: er.EntityRegistry,
) -> None:
    state = hass.states.get(TV)
    assert state.state == "unknown"
    assert state.attributes["commands"][0] == "PowerToggle"
    assert state.attributes["manufacturer"] == "LG"
    assert state.attributes["assumed_state"] is True
    entry = entity_registry.async_get(TV)
    assert entry is not None
    assert entry.unique_id == f"{HUB_ID}:device:70321456_remote"
    device_registry = dr.async_get(hass)
    child = device_registry.async_get_child_device_by_identifier(
        (DOMAIN, f"{HUB_ID}:device:70321456"), init_integration.entry_id
    )
    assert child is not None
    hub = device_registry.async_get_device_by_identifier(
        (DOMAIN, HUB_ID), init_integration.entry_id
    )
    assert child.parent_device_id == hub.id
    assert child.name == "LG OLED TV"

    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: TV}, blocking=True
    )
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: TV}, blocking=True
    )
    await hass.services.async_call(
        REMOTE_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "remote.living_room_hub_soundbar"},
        blocking=True,
    )
    await hass.services.async_call(
        REMOTE_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "remote.living_room_hub_soundbar"},
        blocking=True,
    )
    with pytest.raises(ServiceValidationError, match="has no power command"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "remote.living_room_hub_apple_tv"},
            blocking=True,
        )
    sleep = AsyncMock()
    with patch("custom_components.harmony_ng.remote.asyncio.sleep", sleep):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: TV, ATTR_COMMAND: ["Mute"], ATTR_HOLD_SECS: 0.5},
            blocking=True,
        )
    await hass.services.async_call(DOMAIN, SERVICE_SYNC, {ATTR_ENTITY_ID: TV}, blocking=True)
    assert fake_transport.commands() == [
        ("send_command", ("70321456", "PowerToggle", CommandAction.TAP, 1)),
        ("send_command", ("70321456", "PowerToggle", CommandAction.TAP, 1)),
        ("send_command", ("70321457", "PowerOn", CommandAction.TAP, 1)),
        ("send_command", ("70321457", "PowerOff", CommandAction.TAP, 1)),
        ("send_command", ("70321456", "Mute", CommandAction.PRESS, 1)),
        ("send_command", ("70321456", "Mute", CommandAction.RELEASE, 1)),
        ("push_config", ()),
    ]


async def test_device_remote_follows_inventory(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fake_transport.inventory = Inventory(
        devices=(
            *fake_transport.inventory.devices[:2],
            Device("9", "Projector", "Projector", "Epson", "X", 0, ("PowerToggle",)),
        ),
        version=None,
    )
    fake_transport.push({"type": "config_changed", "files": ["devices"], "seq": 91, "ts": 1})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert hass.states.get("remote.living_room_hub_apple_tv").state == STATE_UNAVAILABLE
    assert hass.states.get("remote.living_room_hub_projector").state == "unknown"
    entity = hass.data["entity_components"]["remote"].get_entity("remote.living_room_hub_apple_tv")
    with pytest.raises(ServiceValidationError, match="No device named 70321458"):
        await entity.async_send_command(["Home"])
    with pytest.raises(ServiceValidationError, match="No device named 70321458"):
        await entity.async_turn_on()


async def test_hub_power_off_not_an_activity(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The Hub lists PowerOff with the activities; the remote reports it only when off."""
    fake_transport.activities = (*fake_transport.activities, POWER_OFF_ACTIVITY)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes["activity_list"] == ["Watch TV", "Listen to Music"]
    assert state.attributes["current_activity"] == "PowerOff"

    fake_transport.push(load_frames("ws_activity_switch")[0])
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["current_activity"] == "Watch TV"
