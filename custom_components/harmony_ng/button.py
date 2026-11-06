"""Buttons of the Hub, its remotes and its configured devices.

The Hub has power off, sync and cancel, plus one button per activity that starts
it. Each remote has wake and sleep. Each configured device has one button per
command it knows, disabled by default: a device knows dozens of commands and
only a few are worth an entity.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity, async_add_dynamic_entities
from .helpers import hub_call
from .pyharmonyng import CAP_RF_WAKE, Activity, CommandAction, Device
from .transport import HarmonyNgTransport


@dataclass(frozen=True, kw_only=True)
class HarmonyNgButtonDescription(ButtonEntityDescription):
    """A Hub button."""

    press_fn: Callable[[HarmonyNgTransport], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class HarmonyNgSlotButtonDescription(ButtonEntityDescription):
    """A button of the remote in one RF slot."""

    press_fn: Callable[[HarmonyNgTransport, int], Awaitable[None]]
    requires: str | None = None
    """Capability the Hub must list for the button to be available."""


HUB_BUTTONS: tuple[HarmonyNgButtonDescription, ...] = (
    HarmonyNgButtonDescription(key="power_off", press_fn=lambda t: t.power_off()),
    HarmonyNgButtonDescription(
        key="sync_remotes",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda t: t.push_config(),
    ),
    HarmonyNgButtonDescription(
        key="cancel_activity",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda t: t.cancel_activity(),
    ),
)

SLOT_BUTTONS: tuple[HarmonyNgSlotButtonDescription, ...] = (
    HarmonyNgSlotButtonDescription(
        key="wake",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda t, slot: t.rf_wake(slot),
        requires=CAP_RF_WAKE,
    ),
    HarmonyNgSlotButtonDescription(
        key="sleep",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda t, slot: t.rf_sleep(slot),
    ),
)


ACTIVITY_DESCRIPTION = ButtonEntityDescription(key="start_activity")
DEVICE_COMMAND_DESCRIPTION = ButtonEntityDescription(
    key="device_command", entity_registry_enabled_default=False
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hub, activity, remote and device command buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(HarmonyNgHubButton(coordinator, d) for d in HUB_BUTTONS)
    entry.async_on_unload(
        async_add_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda state: [slot.slot for slot in state.rf.active_slots],
            lambda coord, slot: [HarmonyNgSlotButton(coord, d, slot) for d in SLOT_BUTTONS],
        )
    )
    entry.async_on_unload(
        async_add_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda state: [activity.id for activity in state.activities],
            lambda coord, activity_id: [HarmonyNgActivityButton(coord, activity_id)],
        )
    )
    entry.async_on_unload(
        async_add_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda state: [
                (device.id, command)
                for device in state.inventory.devices
                for command in device.commands
            ],
            lambda coord, key: [HarmonyNgDeviceCommandButton(coord, *key)],
        )
    )


class HarmonyNgHubButton(HarmonyNgEntity, ButtonEntity):
    """A button of the Hub."""

    entity_description: HarmonyNgButtonDescription

    async def async_press(self) -> None:
        """Run the button's action."""
        await hub_call(self.entity_description.press_fn(self.coordinator.transport))


class HarmonyNgSlotButton(HarmonyNgEntity, ButtonEntity):
    """A button of the remote in one RF slot."""

    entity_description: HarmonyNgSlotButtonDescription

    def __init__(
        self,
        coordinator: HarmonyNgCoordinator,
        description: HarmonyNgSlotButtonDescription,
        slot: int,
    ) -> None:
        """Attach the button to the remote's device."""
        super().__init__(coordinator, description, slot=slot)

    @property
    def available(self) -> bool:
        """Unavailable when the firmware lacks the feature."""
        required = self.entity_description.requires
        return super().available and (required is None or self.state_data.has(required))

    async def async_press(self) -> None:
        """Run the button's action on this slot."""
        await hub_call(
            self.entity_description.press_fn(self.coordinator.transport, self._slot or 0)
        )


class HarmonyNgActivityButton(HarmonyNgEntity, ButtonEntity):
    """Starts one activity of the Hub."""

    def __init__(self, coordinator: HarmonyNgCoordinator, activity_id: str) -> None:
        """Key the button by the activity id, which survives a rename."""
        super().__init__(coordinator, ACTIVITY_DESCRIPTION)
        self._activity_id = activity_id
        self._attr_unique_id = f"{coordinator.hub_id}_activity_{activity_id}"
        # Home Assistant caches entity names: a renamed activity shows after a reload
        activity = self.activity
        self._attr_translation_placeholders = {
            "activity": activity.name if activity else activity_id
        }

    @property
    def activity(self) -> Activity | None:
        """Return the activity as the Hub knows it now."""
        return next((a for a in self.state_data.activities if a.id == self._activity_id), None)

    @property
    def available(self) -> bool:
        """Unavailable once the activity is deleted on the Hub."""
        return super().available and self.activity is not None

    async def async_press(self) -> None:
        """Start the activity."""
        await hub_call(self.coordinator.transport.start_activity(self._activity_id))


class HarmonyNgDeviceCommandButton(HarmonyNgEntity, ButtonEntity):
    """Sends one command of a configured device, as a single tap."""

    def __init__(self, coordinator: HarmonyNgCoordinator, device_id: str, command: str) -> None:
        """Attach the button to the device's child device, named after the command."""
        super().__init__(coordinator, DEVICE_COMMAND_DESCRIPTION)
        self._device_id = device_id
        self._command = command
        self._attr_name = command
        self._attr_unique_id = f"{coordinator.child_identifier(device_id)}_command_{command}"
        self._attr_device_info = coordinator.child_device_info(device_id)

    @property
    def device(self) -> Device | None:
        """Return the device when it still knows the command."""
        device = self.state_data.inventory.device(self._device_id)
        return device if device is not None and device.has_command(self._command) else None

    @property
    def available(self) -> bool:
        """Unavailable once the device or the command left the Hub's inventory."""
        return super().available and self.device is not None

    async def async_press(self) -> None:
        """Send the command once."""
        await hub_call(
            self.coordinator.transport.send_command(
                self._device_id, self._command, CommandAction.TAP, 1
            )
        )
