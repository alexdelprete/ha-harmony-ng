"""Binary sensors: Hub busy, remote charging and sync, Bluetooth host connected."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .const import DOMAIN
from .coordinator import HarmonyNgCoordinator, HubState
from .entity import HarmonyNgEntity, async_add_dynamic_entities
from .pyharmonyng import BtHost, RfSlot


@dataclass(frozen=True, kw_only=True)
class HarmonyNgBinaryDescription(BinarySensorEntityDescription):
    """A Hub binary sensor read from the state."""

    value_fn: Callable[[HubState], bool | None]


@dataclass(frozen=True, kw_only=True)
class HarmonyNgSlotBinaryDescription(BinarySensorEntityDescription):
    """A remote binary sensor read from its RF slot."""

    value_fn: Callable[[RfSlot], bool | None]


HUB_BINARY_SENSORS: tuple[HarmonyNgBinaryDescription, ...] = (
    HarmonyNgBinaryDescription(
        key="busy",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.activity.busy or state.activity.sending,
    ),
)

SLOT_BINARY_SENSORS: tuple[HarmonyNgSlotBinaryDescription, ...] = (
    HarmonyNgSlotBinaryDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda slot: slot.charging,
    ),
    HarmonyNgSlotBinaryDescription(
        key="config_out_of_sync",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda slot: None if slot.in_sync is None else not slot.in_sync,
    ),
)

BT_HOST_DESCRIPTION = BinarySensorEntityDescription(
    key="bt_host",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hub sensors, one set per paired remote and one per Bluetooth host."""
    coordinator = entry.runtime_data.coordinator
    _async_remove_addressless_host(hass, coordinator.hub_id)
    async_add_entities(HarmonyNgHubBinarySensor(coordinator, d) for d in HUB_BINARY_SENSORS)
    entry.async_on_unload(
        async_add_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda state: [slot.slot for slot in state.rf.active_slots],
            lambda coord, slot: [
                HarmonyNgSlotBinarySensor(coord, d, slot) for d in SLOT_BINARY_SENSORS
            ],
        )
    )
    entry.async_on_unload(
        async_add_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda state: [host.bdaddr for host in state.bt.hosts if host.bdaddr],
            lambda coord, bdaddr: [HarmonyNgBtHostSensor(coord, bdaddr)],
        )
    )


class HarmonyNgHubBinarySensor(HarmonyNgEntity, BinarySensorEntity):
    """A binary sensor of the Hub."""

    entity_description: HarmonyNgBinaryDescription

    @property
    def is_on(self) -> bool | None:
        """Return the value read from the state."""
        return self.entity_description.value_fn(self.state_data)


class HarmonyNgSlotBinarySensor(HarmonyNgEntity, BinarySensorEntity):
    """A binary sensor of the remote in one RF slot."""

    entity_description: HarmonyNgSlotBinaryDescription

    def __init__(
        self,
        coordinator: HarmonyNgCoordinator,
        description: HarmonyNgSlotBinaryDescription,
        slot: int,
    ) -> None:
        """Attach the sensor to the remote's device."""
        super().__init__(coordinator, description, slot=slot)

    @property
    def is_on(self) -> bool | None:
        """Return the value read from the slot."""
        rf_slot = self.state_data.slot(self._slot or 0)
        return self.entity_description.value_fn(rf_slot) if rf_slot else None


class HarmonyNgBtHostSensor(HarmonyNgEntity, BinarySensorEntity):
    """Whether one paired Bluetooth host is connected to the Hub."""

    def __init__(self, coordinator: HarmonyNgCoordinator, bdaddr: str) -> None:
        """Key the sensor by the host's address; name it after the host."""
        super().__init__(coordinator, BT_HOST_DESCRIPTION)
        self._bdaddr = bdaddr
        self._attr_unique_id = f"{coordinator.hub_id}_bt_host_{_address_key(bdaddr)}"
        self._attr_translation_placeholders = {"name": self._host_name()}

    def _host(self) -> BtHost | None:
        wanted = self._bdaddr.casefold()
        return next((h for h in self.state_data.bt.hosts if h.bdaddr.casefold() == wanted), None)

    def _host_name(self) -> str:
        host = self._host()
        return host.name if host and host.name else self._bdaddr

    @property
    def available(self) -> bool:
        """Unavailable once the host is no longer paired."""
        return super().available and self._host() is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the host is connected."""
        host = self._host()
        return host.connected if host else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the host's address and name."""
        return {"bdaddr": self._bdaddr, "name": self._host_name()}


def _address_key(bdaddr: str) -> str:
    return bdaddr.replace(":", "").lower()


def _async_remove_addressless_host(hass: HomeAssistant, hub_id: str) -> None:
    """Remove the host sensor 0.1.1 and earlier created for hosts without an address.

    Those releases read the address from a key the Hub does not send, so every
    host got the same empty address and a single sensor stood for all of them.
    """
    registry = er.async_get(hass)
    stale = registry.async_get_entity_id(BINARY_SENSOR_DOMAIN, DOMAIN, f"{hub_id}_bt_host_")
    if stale is not None:
        registry.async_remove(stale)
