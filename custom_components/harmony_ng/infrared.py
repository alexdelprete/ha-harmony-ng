"""Infrared emitters and receiver.

Home Assistant's infrared platform hands an emitter a command with a carrier and
raw timings; the Hub sends them through its raw IR endpoint, so core infrared
integrations can use the Hub as their blaster. The receiver turns the Hub's
capture on while it is enabled and republishes every captured signal.
"""

from __future__ import annotations

import logging

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredEmitterEntity,
    InfraredEmitterEntityDescription,
    InfraredReceivedSignal,
    InfraredReceiverEntity,
    InfraredReceiverEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .const import IR_EMITTERS
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity
from .helpers import hub_call
from .pyharmonyng import CAP_IR_CAPTURE, CAP_IR_RAW, HarmonyNgError, IrSignal

_LOGGER = logging.getLogger(__name__)

EMITTERS: tuple[InfraredEmitterEntityDescription, ...] = tuple(
    InfraredEmitterEntityDescription(key=key, entity_registry_enabled_default=(port == 1))
    for key, port in IR_EMITTERS.items()
)
RECEIVER = InfraredReceiverEntityDescription(
    key="ir_receiver", entity_registry_enabled_default=False
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one emitter per infrared output and the receiver."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            *(HarmonyNgInfraredEmitter(coordinator, d) for d in EMITTERS),
            HarmonyNgInfraredReceiver(coordinator),
        ]
    )


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


class HarmonyNgInfraredReceiver(HarmonyNgEntity, InfraredReceiverEntity):
    """The Hub's infrared capture, on while this entity is enabled.

    Disabled by default: capturing shares the infrared hardware with sending, so
    only users who want to learn codes turn it on.
    """

    entity_description: InfraredReceiverEntityDescription

    def __init__(self, coordinator: HarmonyNgCoordinator) -> None:
        """Create the receiver of the Hub."""
        super().__init__(coordinator, RECEIVER)

    @property
    def available(self) -> bool:
        """Unavailable when the firmware cannot capture."""
        return super().available and self.state_data.has(CAP_IR_CAPTURE)

    async def async_added_to_hass(self) -> None:
        """Subscribe to captured signals and turn the Hub's capture on."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_ir_listener(self._handle_signal))
        await self._async_set_capture(True)

    async def async_will_remove_from_hass(self) -> None:
        """Turn the Hub's capture off."""
        await self._async_set_capture(False)
        await super().async_will_remove_from_hass()

    async def _async_set_capture(self, enabled: bool) -> None:
        if not self.available:
            return
        try:
            await self.coordinator.transport.ir_capture(enabled)
        except HarmonyNgError as err:
            _LOGGER.warning(
                "Could not %s infrared capture: %s", "start" if enabled else "stop", err
            )

    @callback
    def _handle_signal(self, signal: IrSignal) -> None:
        self._handle_received_signal(
            InfraredReceivedSignal(timings=list(signal.timings), modulation=signal.modulation)
        )
