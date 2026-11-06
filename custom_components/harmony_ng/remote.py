"""The remote entity: activities and device commands, as the core integration exposes them."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_ACTIVITY,
    ATTR_DELAY_SECS,
    ATTR_DEVICE,
    ATTR_HOLD_SECS,
    ATTR_NUM_REPEATS,
    DOMAIN as REMOTE_DOMAIN,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.service import async_register_platform_entity_service

from . import HarmonyNgConfigEntry
from .const import (
    CONF_DEFAULT_ACTIVITY,
    CONF_DELAY_SECS,
    DEFAULT_DELAY_SECS,
    DOMAIN,
    PREVIOUS_ACTIVITY,
    SERVICE_SYNC,
)
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity
from .helpers import hub_call, resolve_activity, resolve_command, resolve_device
from .pyharmonyng import ActivityStatus, CommandAction

ATTR_LAST_ACTIVITY = "last_activity"
ATTR_ACTIVITY_STARTING = "activity_starting"
ATTR_DEVICES_LIST = "devices_list"

REMOTE_DESCRIPTION = EntityDescription(key="remote")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hub's remote entity and its sync service."""
    async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SYNC,
        entity_domain=REMOTE_DOMAIN,
        func="async_sync",
        schema=None,
    )
    async_add_entities([HarmonyNgRemote(entry.runtime_data.coordinator)])


class HarmonyNgRemote(HarmonyNgEntity, RemoteEntity):
    """The Hub as a remote: turn on an activity, power off, send commands."""

    _attr_name = None
    _attr_supported_features = RemoteEntityFeature.ACTIVITY

    def __init__(self, coordinator: HarmonyNgCoordinator) -> None:
        """Create the Hub's main entity."""
        super().__init__(coordinator, REMOTE_DESCRIPTION)

    @property
    def is_on(self) -> bool:
        """Return whether an activity is selected."""
        return self.state_data.activity.is_on

    @property
    def current_activity(self) -> str | None:
        """Return the running activity's name."""
        state = self.state_data
        return state.activity_name(state.activity.activity_id)

    @property
    def activity_list(self) -> list[str]:
        """Return the activity names."""
        return [activity.name for activity in self.state_data.activities]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Keep the attributes the core integration exposes."""
        state = self.state_data
        return {
            ATTR_LAST_ACTIVITY: (
                state.activity_name(state.last_activity_id) if state.last_activity_id else None
            ),
            ATTR_ACTIVITY_STARTING: state.activity.state is ActivityStatus.STARTING,
            ATTR_DEVICES_LIST: [device.name for device in state.inventory.devices],
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the given activity, else the default one from the options."""
        activity = kwargs.get(ATTR_ACTIVITY) or self._default_activity()
        if not activity:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_activity")
        target = resolve_activity(self.state_data, activity)
        await hub_call(self.coordinator.transport.start_activity(target.id))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power off."""
        await hub_call(self.coordinator.transport.power_off())

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send device commands with the core integration's semantics.

        `device` names the inventory device by name or id. `hold_secs` turns each
        command into a press, a wait and a release. `delay_secs` separates commands
        and `num_repeats` repeats the whole list.
        """
        device_name = kwargs.get(ATTR_DEVICE)
        if not device_name:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="device_required"
            )
        device = resolve_device(self.state_data, str(device_name))
        commands = [resolve_command(device, name) for name in command]
        repeats = int(kwargs.get(ATTR_NUM_REPEATS) or 1)
        delay = float(
            kwargs.get(ATTR_DELAY_SECS)
            or self.coordinator.config_entry.options.get(CONF_DELAY_SECS, DEFAULT_DELAY_SECS)
        )
        hold = float(kwargs.get(ATTR_HOLD_SECS) or 0)
        transport = self.coordinator.transport
        first = True
        for _ in range(repeats):
            for name in commands:
                if not first:
                    await asyncio.sleep(delay)
                first = False
                if hold > 0:
                    await hub_call(transport.send_command(device.id, name, CommandAction.PRESS, 1))
                    await asyncio.sleep(hold)
                    await hub_call(
                        transport.send_command(device.id, name, CommandAction.RELEASE, 1)
                    )
                else:
                    await hub_call(transport.send_command(device.id, name, CommandAction.TAP, 1))

    async def async_sync(self) -> None:
        """Push the configuration to the remotes (harmony_ng.sync)."""
        await hub_call(self.coordinator.transport.push_config())

    @callback
    def _default_activity(self) -> str | None:
        option = self.coordinator.config_entry.options.get(CONF_DEFAULT_ACTIVITY)
        if option in (None, PREVIOUS_ACTIVITY):
            return self.state_data.last_activity_id
        return str(option)
