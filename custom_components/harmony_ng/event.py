"""Event entity: the keys pressed and released on each remote."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity, async_add_dynamic_entities
from .pyharmonyng import RemoteButton

EVENT_PRESS = "press"
EVENT_RELEASE = "release"

BUTTON_DESCRIPTION = EventEntityDescription(
    key="button",
    device_class=EventDeviceClass.BUTTON,
    event_types=[EVENT_PRESS, EVENT_RELEASE],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one button event entity per paired remote."""
    entry.async_on_unload(
        async_add_dynamic_entities(
            entry.runtime_data.coordinator,
            async_add_entities,
            lambda state: [slot.slot for slot in state.rf.active_slots],
            lambda coord, slot: [HarmonyNgButtonEvent(coord, slot)],
        )
    )


class HarmonyNgButtonEvent(HarmonyNgEntity, EventEntity):
    """Fires for every key press and release on the remote in one slot."""

    entity_description: EventEntityDescription

    def __init__(self, coordinator: HarmonyNgCoordinator, slot: int) -> None:
        """Attach the entity to the remote's device."""
        super().__init__(coordinator, BUTTON_DESCRIPTION, slot=slot)

    async def async_added_to_hass(self) -> None:
        """Subscribe to the remote's buttons while the entity lives."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_button_listener(self._slot or 0, self._handle_button)
        )

    @callback
    def _handle_button(self, button: RemoteButton) -> None:
        if button.action not in (EVENT_PRESS, EVENT_RELEASE):
            return
        self._trigger_event(
            button.action,
            {
                "button": button.button,
                "device_id": button.device_id,
                "command": button.command,
                "source": button.source,
            },
        )
        self.async_write_ha_state()
