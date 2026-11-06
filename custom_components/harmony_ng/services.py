"""Integration services: raw device commands, Bluetooth keys, Help and cancel."""

from __future__ import annotations

from typing import Any

import probatio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import (
    ATTR_ACTION,
    ATTR_COMMAND,
    ATTR_DEVICE,
    ATTR_KEY,
    ATTR_ON,
    ATTR_PORT,
    ATTR_REPEATS,
    ATTR_TARGET,
    DOMAIN,
    IR_PORTS,
    MAX_REPEATS,
    SERVICE_ACTIVITY_CANCEL,
    SERVICE_ACTIVITY_HELP,
    SERVICE_ACTIVITY_HELP_ANSWER,
    SERVICE_BT_KEY,
    SERVICE_IR_SEND,
)
from .coordinator import HarmonyNgCoordinator
from .helpers import hub_call, resolve_command, resolve_device
from .pyharmonyng import KeyAction

KEY_ACTIONS = {
    "tap": KeyAction.TAP,
    "press": KeyAction.DOWN,
    "release": KeyAction.UP,
    "release_all": KeyAction.RELEASE_ALL,
}

TARGET_SCHEMA = {probatio.Required(ATTR_DEVICE_ID): cv.string}

IR_SEND_SCHEMA = probatio.Schema(
    {
        **TARGET_SCHEMA,
        probatio.Required(ATTR_DEVICE): cv.string,
        probatio.Required(ATTR_COMMAND): cv.string,
        probatio.Optional(ATTR_PORT, default="all"): probatio.In(list(IR_PORTS)),
        probatio.Optional(ATTR_REPEATS, default=1): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=MAX_REPEATS)
        ),
    }
)
BT_KEY_SCHEMA = probatio.Schema(
    {
        **TARGET_SCHEMA,
        probatio.Required(ATTR_KEY): cv.string,
        probatio.Optional(ATTR_ACTION, default="tap"): probatio.In(list(KEY_ACTIONS)),
        probatio.Optional(ATTR_TARGET): cv.string,
    }
)
HELP_ANSWER_SCHEMA = probatio.Schema(
    {
        **TARGET_SCHEMA,
        probatio.Required(ATTR_DEVICE): cv.string,
        probatio.Required(ATTR_ON): cv.boolean,
    }
)
TARGET_ONLY_SCHEMA = probatio.Schema(TARGET_SCHEMA)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services; they resolve the Hub from the targeted device."""
    hass.services.async_register(DOMAIN, SERVICE_IR_SEND, _async_ir_send, schema=IR_SEND_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_BT_KEY, _async_bt_key, schema=BT_KEY_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVITY_HELP,
        _async_activity_help,
        schema=TARGET_ONLY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ACTIVITY_HELP_ANSWER, _async_activity_help_answer, schema=HELP_ANSWER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ACTIVITY_CANCEL, _async_activity_cancel, schema=TARGET_ONLY_SCHEMA
    )


@callback
def _coordinator_for(call: ServiceCall) -> HarmonyNgCoordinator:
    """Return the coordinator of the Hub that owns the targeted device."""
    device_id: str = call.data[ATTR_DEVICE_ID]
    device = dr.async_get(call.hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="target_not_found",
            translation_placeholders={"device_id": device_id},
        )
    for entry_id in device.config_entries:
        entry = call.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            continue
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"name": entry.title},
            )
        return entry.runtime_data.coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="target_not_found",
        translation_placeholders={"device_id": device_id},
    )


async def _async_ir_send(call: ServiceCall) -> None:
    coordinator = _coordinator_for(call)
    device = resolve_device(coordinator.data, call.data[ATTR_DEVICE])
    command = resolve_command(device, call.data[ATTR_COMMAND])
    await hub_call(
        coordinator.transport.ir_send(
            device.id, command, IR_PORTS[call.data[ATTR_PORT]], call.data[ATTR_REPEATS]
        )
    )


async def _async_bt_key(call: ServiceCall) -> None:
    coordinator = _coordinator_for(call)
    await hub_call(
        coordinator.transport.bt_key(
            call.data[ATTR_KEY], KEY_ACTIONS[call.data[ATTR_ACTION]], call.data.get(ATTR_TARGET)
        )
    )


async def _async_activity_help(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator_for(call)
    result = await hub_call(coordinator.transport.activity_help())
    response: dict[str, Any] = {
        "activity": result.activity_id,
        "devices": [
            {"id": d.id, "name": d.name, "command": d.command} for d in result.toggle_devices
        ],
    }
    return response if call.return_response else None


async def _async_activity_help_answer(call: ServiceCall) -> None:
    coordinator = _coordinator_for(call)
    device = resolve_device(coordinator.data, call.data[ATTR_DEVICE])
    await hub_call(coordinator.transport.activity_help_answer(device.id, call.data[ATTR_ON]))


async def _async_activity_cancel(call: ServiceCall) -> None:
    coordinator = _coordinator_for(call)
    await hub_call(coordinator.transport.cancel_activity())
