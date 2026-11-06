"""Shared helpers: error translation and lookups."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN
from .coordinator import HubState
from .pyharmonyng import (
    Activity,
    Device,
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
    HarmonyNgError,
)


def hub_error(err: HarmonyNgError) -> HomeAssistantError:
    """Return the translated Home Assistant error for a library error."""
    if isinstance(err, HarmonyNgBusyError):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="hub_busy")
    if isinstance(err, HarmonyNgAuthError):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed")
    if isinstance(err, HarmonyNgConnectionError):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        )
    message = err.message if isinstance(err, HarmonyNgApiError) else str(err)
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="hub_error",
        translation_placeholders={"error": message},
    )


async def hub_call[T](awaitable: Awaitable[T]) -> T:
    """Await a transport call, translating library errors for the user."""
    try:
        return await awaitable
    except HarmonyNgError as err:
        raise hub_error(err) from err


def resolve_device(state: HubState, device: str) -> Device:
    """Return the inventory device named or identified by `device`."""
    found = state.inventory.device(device) or state.inventory.device_by_name(device)
    if found is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device": device},
        )
    return found


def resolve_command(device: Device, command: str) -> str:
    """Return the device's command name matching `command`, case-insensitively."""
    wanted = command.casefold()
    for name in device.commands:
        if name.casefold() == wanted:
            return name
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="command_not_found",
        translation_placeholders={"command": command, "device": device.name},
    )


def resolve_activity(state: HubState, activity: str) -> Activity:
    """Return the activity named or identified by `activity`."""
    found = state.activity_by_id(activity) or state.activity_by_name(activity)
    if found is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="activity_not_found",
            translation_placeholders={"activity": activity},
        )
    return found
