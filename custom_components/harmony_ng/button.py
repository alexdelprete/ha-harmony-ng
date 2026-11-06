"""Buttons: power off, sync and cancel on the Hub; wake and sleep on each remote."""

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
from .pyharmonyng import CAP_RF_WAKE
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hub buttons and a pair per paired remote."""
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
