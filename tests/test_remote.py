"""Tests for the remote entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.const import (
    CONF_DEFAULT_ACTIVITY,
    CONF_DELAY_SECS,
    DOMAIN,
    SERVICE_SYNC,
)
from custom_components.harmony_ng.pyharmonyng import (
    CommandAction,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
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
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTransport
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
