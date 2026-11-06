"""Tests for the integration services."""

from __future__ import annotations

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.harmony_ng.const import (
    ATTR_ACTION,
    ATTR_COMMAND,
    ATTR_DEVICE,
    ATTR_KEY,
    ATTR_ON,
    ATTR_PORT,
    ATTR_REPEATS,
    ATTR_TARGET,
    DOMAIN,
    SERVICE_ACTIVITY_CANCEL,
    SERVICE_ACTIVITY_HELP,
    SERVICE_ACTIVITY_HELP_ANSWER,
    SERVICE_BT_KEY,
    SERVICE_IR_SEND,
)
from custom_components.harmony_ng.pyharmonyng import HarmonyNgBusyError, KeyAction
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from .conftest import HUB_ID, FakeTransport


def hub_device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, HUB_ID), entry.entry_id)
    assert device is not None
    return device.id


async def test_ir_send(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    target = hub_device_id(hass, init_integration)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_IR_SEND,
        {ATTR_DEVICE_ID: target, ATTR_DEVICE: "lg oled tv", ATTR_COMMAND: "mute"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_IR_SEND,
        {
            ATTR_DEVICE_ID: target,
            ATTR_DEVICE: "70321457",
            ATTR_COMMAND: "PowerOn",
            ATTR_PORT: "jack1",
            ATTR_REPEATS: 3,
        },
        blocking=True,
    )
    assert fake_transport.commands() == [
        ("ir_send", ("70321456", "Mute", 7, 1)),
        ("ir_send", ("70321457", "PowerOn", 2, 3)),
    ]
    with pytest.raises(ServiceValidationError, match="has no command named Play"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_IR_SEND,
            {ATTR_DEVICE_ID: target, ATTR_DEVICE: "LG OLED TV", ATTR_COMMAND: "Play"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="No device named Nope"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_IR_SEND,
            {ATTR_DEVICE_ID: target, ATTR_DEVICE: "Nope", ATTR_COMMAND: "Play"},
            blocking=True,
        )


async def test_bt_key(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    target = hub_device_id(hass, init_integration)
    await hass.services.async_call(
        DOMAIN, SERVICE_BT_KEY, {ATTR_DEVICE_ID: target, ATTR_KEY: "KEY_ENTER"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_BT_KEY,
        {
            ATTR_DEVICE_ID: target,
            ATTR_KEY: "KEY_UP",
            ATTR_ACTION: "press",
            ATTR_TARGET: "AA:BB:CC:DD:EE:FF",
        },
        blocking=True,
    )
    assert fake_transport.commands() == [
        ("bt_key", ("KEY_ENTER", KeyAction.TAP, None)),
        ("bt_key", ("KEY_UP", KeyAction.DOWN, "AA:BB:CC:DD:EE:FF")),
    ]


async def test_help_and_cancel(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    target = hub_device_id(hass, init_integration)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_ACTIVITY_HELP,
        {ATTR_DEVICE_ID: target},
        blocking=True,
        return_response=True,
    )
    assert response == {
        "activity": "123456",
        "devices": [{"id": "70321456", "name": "LG OLED TV", "command": "PowerToggle"}],
    }
    await hass.services.async_call(
        DOMAIN, SERVICE_ACTIVITY_HELP, {ATTR_DEVICE_ID: target}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ACTIVITY_HELP_ANSWER,
        {ATTR_DEVICE_ID: target, ATTR_DEVICE: "LG OLED TV", ATTR_ON: False},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, SERVICE_ACTIVITY_CANCEL, {ATTR_DEVICE_ID: target}, blocking=True
    )
    assert fake_transport.commands() == [
        ("activity_help", ()),
        ("activity_help", ()),
        ("activity_help_answer", ("70321456", False)),
        ("cancel_activity", ()),
    ]
    fake_transport.errors["cancel_activity"] = HarmonyNgBusyError("busy")
    with pytest.raises(HomeAssistantError, match="busy"):
        await hass.services.async_call(
            DOMAIN, SERVICE_ACTIVITY_CANCEL, {ATTR_DEVICE_ID: target}, blocking=True
        )


async def test_target_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    with pytest.raises(ServiceValidationError, match="does not belong"):
        await hass.services.async_call(
            DOMAIN, SERVICE_ACTIVITY_CANCEL, {ATTR_DEVICE_ID: "nope"}, blocking=True
        )
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "x")}
    )
    with pytest.raises(ServiceValidationError, match="does not belong"):
        await hass.services.async_call(
            DOMAIN, SERVICE_ACTIVITY_CANCEL, {ATTR_DEVICE_ID: device.id}, blocking=True
        )
    target = hub_device_id(hass, init_integration)
    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="is not loaded"):
        await hass.services.async_call(
            DOMAIN, SERVICE_ACTIVITY_CANCEL, {ATTR_DEVICE_ID: target}, blocking=True
        )
