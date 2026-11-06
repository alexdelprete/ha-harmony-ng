"""Activity select: the activity names plus PowerOff, as the core integration offers."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .const import POWER_OFF_LABEL
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity
from .helpers import hub_call, resolve_activity

ACTIVITY_DESCRIPTION = SelectEntityDescription(key="activity")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the activity select."""
    async_add_entities([HarmonyNgActivitySelect(entry.runtime_data.coordinator)])


class HarmonyNgActivitySelect(HarmonyNgEntity, SelectEntity):
    """Pick the running activity."""

    def __init__(self, coordinator: HarmonyNgCoordinator) -> None:
        """Create the Hub's activity select."""
        super().__init__(coordinator, ACTIVITY_DESCRIPTION)

    @property
    def options(self) -> list[str]:
        """Return PowerOff and the activity names."""
        return [POWER_OFF_LABEL, *(activity.name for activity in self.state_data.activities)]

    @property
    def current_option(self) -> str:
        """Return the running activity's name, or PowerOff."""
        state = self.state_data
        return state.activity_name(state.activity.activity_id) or POWER_OFF_LABEL

    async def async_select_option(self, option: str) -> None:
        """Start the chosen activity, or power off."""
        if option == POWER_OFF_LABEL:
            await hub_call(self.coordinator.transport.power_off())
            return
        activity = resolve_activity(self.state_data, option)
        await hub_call(self.coordinator.transport.start_activity(activity.id))
