"""Infrared emitters: the Hub's front blaster and its two emitter jacks.

Home Assistant's infrared platform hands the entity a command with a carrier and
raw timings; the Hub sends them through its raw IR endpoint, so core infrared
integrations can use the Hub as their blaster.
"""

from __future__ import annotations

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredEmitterEntity,
    InfraredEmitterEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .const import IR_EMITTERS
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity
from .helpers import hub_call
from .pyharmonyng import CAP_IR_RAW

EMITTERS: tuple[InfraredEmitterEntityDescription, ...] = tuple(
    InfraredEmitterEntityDescription(key=key, entity_registry_enabled_default=(port == 1))
    for key, port in IR_EMITTERS.items()
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one emitter per infrared output."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(HarmonyNgInfraredEmitter(coordinator, d) for d in EMITTERS)


class HarmonyNgInfraredEmitter(HarmonyNgEntity, InfraredEmitterEntity):
    """One infrared output of the Hub."""

    entity_description: InfraredEmitterEntityDescription

    def __init__(
        self, coordinator: HarmonyNgCoordinator, description: InfraredEmitterEntityDescription
    ) -> None:
        """Keep the output's port mask."""
        super().__init__(coordinator, description)
        self._port = IR_EMITTERS[description.key]

    @property
    def available(self) -> bool:
        """Unavailable when the firmware has no raw infrared endpoint."""
        return super().available and self.state_data.has(CAP_IR_RAW)

    async def async_send_command(self, command: InfraredCommand) -> None:
        """Send the command's raw timings on this output."""
        await hub_call(
            self.coordinator.transport.ir_raw(
                command.modulation,
                command.get_raw_timings(),
                self._port,
                max(1, command.repeat_count),
            )
        )
