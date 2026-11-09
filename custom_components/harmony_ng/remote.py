"""Remote entities: the Hub, and one per configured device under it.

The Hub's remote keeps the attributes and services of the core Harmony
integration. Each configured IR or Bluetooth device is a child device of the Hub
with its own remote, so `remote.send_command` can target the device directly.
"""

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
    POWER_OFF_LABEL,
    PREVIOUS_ACTIVITY,
    SERVICE_SYNC,
)
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity, async_add_dynamic_entities
from .helpers import hub_call, resolve_activity, resolve_command, resolve_device
from .pyharmonyng import POWER_OFF_ACTIVITY_ID, ActivityStatus, CommandAction, Device
from .transport import HarmonyNgTransport

ATTR_LAST_ACTIVITY = "last_activity"
ATTR_ACTIVITY_STARTING = "activity_starting"
ATTR_ACTIVITY_QUEUED = "activity_queued"
ATTR_DEVICES_LIST = "devices_list"
ATTR_COMMANDS = "commands"

REMOTE_DESCRIPTION = EntityDescription(key="remote")
DEVICE_REMOTE_DESCRIPTION = EntityDescription(key="remote")

POWER_ON_COMMANDS = ("PowerOn", "PowerToggle")
POWER_OFF_COMMANDS = ("PowerOff", "PowerToggle")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hub's remote, its sync service, and a remote per configured device."""
    async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SYNC,
        entity_domain=REMOTE_DOMAIN,
        func="async_sync",
        schema=None,
    )
    coordinator = entry.runtime_data.coordinator
    async_add_entities([HarmonyNgRemote(coordinator)])
    entry.async_on_unload(
        async_add_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda state: [device.id for device in state.inventory.devices],
            lambda coord, device_id: [HarmonyNgDeviceRemote(coord, device_id)],
        )
    )


async def async_send_commands(
    transport: HarmonyNgTransport,
    device: Device,
    commands: Iterable[str],
    *,
    repeats: int,
    delay: float,
    hold: float,
) -> None:
    """Send commands with the core integration's semantics.

    `hold` turns each command into a press, a wait and a release. `delay`
    separates commands and `repeats` repeats the whole list.
    """
    names = [resolve_command(device, name) for name in commands]
    first = True
    for _ in range(max(1, repeats)):
        for name in names:
            if not first:
                await asyncio.sleep(delay)
            first = False
            if hold > 0:
                await hub_call(transport.send_command(device.id, name, CommandAction.PRESS, 1))
                await asyncio.sleep(hold)
                await hub_call(transport.send_command(device.id, name, CommandAction.RELEASE, 1))
            else:
                await hub_call(transport.send_command(device.id, name, CommandAction.TAP, 1))


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
        """Return the running activity's name, or PowerOff as the core integration does."""
        state = self.state_data
        if not state.activity.is_on:
            return POWER_OFF_LABEL
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
            ATTR_ACTIVITY_QUEUED: self._queued_activity(),
            ATTR_DEVICES_LIST: [device.name for device in state.inventory.devices],
        }

    def _queued_activity(self) -> str | None:
        """Return the activity the Hub starts when the running transition completes."""
        state = self.state_data
        queued = state.activity.queued
        if queued is None:
            return None
        if queued == POWER_OFF_ACTIVITY_ID:
            return POWER_OFF_LABEL
        return state.activity_name(queued) or queued

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
        """Send device commands; `device` names the inventory device by name or id."""
        device_name = kwargs.get(ATTR_DEVICE)
        if not device_name:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="device_required"
            )
        device = resolve_device(self.state_data, str(device_name))
        await async_send_commands(
            self.coordinator.transport,
            device,
            command,
            repeats=int(kwargs.get(ATTR_NUM_REPEATS) or 1),
            delay=self._delay(kwargs),
            hold=float(kwargs.get(ATTR_HOLD_SECS) or 0),
        )

    async def async_sync(self) -> None:
        """Push the configuration to the remotes (harmony_ng.sync)."""
        await hub_call(self.coordinator.transport.push_config())

    def _delay(self, kwargs: dict[str, Any]) -> float:
        return float(
            kwargs.get(ATTR_DELAY_SECS)
            or self.coordinator.config_entry.options.get(CONF_DELAY_SECS, DEFAULT_DELAY_SECS)
        )

    @callback
    def _default_activity(self) -> str | None:
        option = self.coordinator.config_entry.options.get(CONF_DEFAULT_ACTIVITY)
        if option in (None, PREVIOUS_ACTIVITY):
            return self.state_data.last_activity_id
        return str(option)


class HarmonyNgDeviceRemote(HarmonyNgEntity, RemoteEntity):
    """A configured device of the Hub, as a remote of its own.

    The device has no state the Hub can read, so the entity's state stays
    unknown; its value is `remote.send_command` without naming the device, and
    power on and off through the device's power commands.
    """

    _attr_name = None
    _attr_assumed_state = True

    def __init__(self, coordinator: HarmonyNgCoordinator, device_id: str) -> None:
        """Create the remote of one configured device, as a child device of the Hub."""
        super().__init__(coordinator, DEVICE_REMOTE_DESCRIPTION)
        self._device_id = device_id
        self._attr_unique_id = f"{coordinator.child_identifier(device_id)}_remote"
        self._attr_device_info = coordinator.child_device_info(device_id)

    @property
    def device(self) -> Device | None:
        """Return the device as the inventory knows it now."""
        return self.state_data.inventory.device(self._device_id)

    @property
    def available(self) -> bool:
        """Unavailable once the device left the Hub's inventory."""
        return super().available and self.device is not None

    @property
    def is_on(self) -> bool | None:
        """The Hub cannot read the device's power state."""
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose what the inventory says about the device."""
        device = self.device
        if device is None:
            return {}
        return {
            ATTR_COMMANDS: list(device.commands),
            "manufacturer": device.manufacturer,
            "model": device.model,
            "type": device.type,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the device's power on command, else its power toggle."""
        await self._async_power(POWER_ON_COMMANDS)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the device's power off command, else its power toggle."""
        await self._async_power(POWER_OFF_COMMANDS)

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send commands to this device; the `device` field is not needed."""
        device = self._require_device()
        await async_send_commands(
            self.coordinator.transport,
            device,
            command,
            repeats=int(kwargs.get(ATTR_NUM_REPEATS) or 1),
            delay=float(
                kwargs.get(ATTR_DELAY_SECS)
                or self.coordinator.config_entry.options.get(CONF_DELAY_SECS, DEFAULT_DELAY_SECS)
            ),
            hold=float(kwargs.get(ATTR_HOLD_SECS) or 0),
        )

    async def async_sync(self) -> None:
        """Push the configuration to the remotes (harmony_ng.sync)."""
        await hub_call(self.coordinator.transport.push_config())

    def _require_device(self) -> Device:
        device = self.device
        if device is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device": self._device_id},
            )
        return device

    async def _async_power(self, candidates: tuple[str, ...]) -> None:
        device = self._require_device()
        name = next((c for c in candidates if device.has_command(c)), None)
        if name is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_power_command",
                translation_placeholders={"device": device.name},
            )
        await async_send_commands(
            self.coordinator.transport, device, [name], repeats=1, delay=0, hold=0
        )
