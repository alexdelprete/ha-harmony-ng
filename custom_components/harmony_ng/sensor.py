"""Sensors: activity state, firmware and uptime of the Hub; battery of each remote."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import HarmonyNgConfigEntry
from .coordinator import HarmonyNgCoordinator, HubState
from .entity import HarmonyNgEntity, async_add_remote_entities
from .pyharmonyng import ActivityStatus, RfSlot


@dataclass(frozen=True, kw_only=True)
class HarmonyNgSensorDescription(SensorEntityDescription):
    """A Hub sensor read from the state."""

    value_fn: Callable[[HubState], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class HarmonyNgSlotSensorDescription(SensorEntityDescription):
    """A remote sensor read from its RF slot."""

    value_fn: Callable[[RfSlot], StateType | datetime]


HUB_SENSORS: tuple[HarmonyNgSensorDescription, ...] = (
    HarmonyNgSensorDescription(
        key="activity_state",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in ActivityStatus],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.activity.state.value,
    ),
    HarmonyNgSensorDescription(
        key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.hub.version or None,
    ),
    HarmonyNgSensorDescription(
        key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # The Hub's boot_time, or once per snapshot from its uptime on older firmware
        value_fn=lambda state: state.booted_at,
    ),
)

SLOT_SENSORS: tuple[HarmonyNgSlotSensorDescription, ...] = (
    HarmonyNgSlotSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda slot: slot.battery_percent,
    ),
    HarmonyNgSlotSensorDescription(
        key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        # "3.70 V" rather than "3701 mV", which a locale with a dot as the thousands
        # separator renders as "3.701 mV"
        suggested_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda slot: slot.voltage_mv,
    ),
    HarmonyNgSlotSensorDescription(
        key="battery_reported_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda slot: slot.battery_reported_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hub sensors, and a battery sensor set for every paired remote."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(HarmonyNgHubSensor(coordinator, desc) for desc in HUB_SENSORS)
    entry.async_on_unload(
        async_add_remote_entities(
            coordinator,
            async_add_entities,
            lambda coord, slot: [HarmonyNgSlotSensor(coord, desc, slot) for desc in SLOT_SENSORS],
        )
    )


class HarmonyNgHubSensor(HarmonyNgEntity, SensorEntity):
    """A sensor of the Hub."""

    entity_description: HarmonyNgSensorDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value read from the state."""
        return self.entity_description.value_fn(self.state_data)


class HarmonyNgSlotSensor(HarmonyNgEntity, SensorEntity):
    """A sensor of the remote in one RF slot."""

    entity_description: HarmonyNgSlotSensorDescription

    def __init__(
        self,
        coordinator: HarmonyNgCoordinator,
        description: HarmonyNgSlotSensorDescription,
        slot: int,
    ) -> None:
        """Attach the sensor to the remote's device."""
        super().__init__(coordinator, description, slot=slot)

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value read from the slot."""
        rf_slot = self.state_data.slot(self._slot or 0)
        return self.entity_description.value_fn(rf_slot) if rf_slot else None
