"""Base entity for Harmony NG."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging

from homeassistant.core import callback
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HarmonyNgCoordinator, HubState

_LOGGER = logging.getLogger(__name__)


class HarmonyNgEntity(CoordinatorEntity[HarmonyNgCoordinator]):
    """Base class for every Harmony NG entity.

    An entity belongs to the Hub, or to the remote in an RF slot. Unique ids are the
    owner's identifier plus the entity key and never carry the transport, host or
    port, so the transport can change without touching the registry.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HarmonyNgCoordinator,
        description: EntityDescription,
        *,
        slot: int | None = None,
    ) -> None:
        """Key the entity by its owner and description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._slot = slot
        if slot is None:
            owner = coordinator.hub_id
            self._attr_device_info = coordinator.hub_device_info()
        else:
            owner = coordinator.remote_identifier(slot)
            self._attr_device_info = coordinator.remote_device_info(slot)
        self._attr_unique_id = f"{owner}_{description.key}"
        self._attr_translation_key = description.translation_key or description.key

    @property
    def state_data(self) -> HubState:
        """Return the coordinator's state."""
        return self.coordinator.data

    @property
    def slot(self) -> int | None:
        """Return the RF slot this entity belongs to, if any."""
        return self._slot

    @property
    def available(self) -> bool:
        """Unavailable while the Hub is unreachable, or while the slot has no remote."""
        if not super().available or not self.coordinator.data.connected:
            return False
        if self._slot is None:
            return True
        rf_slot = self.coordinator.data.slot(self._slot)
        return rf_slot is not None and rf_slot.active

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Nothing here is keyed on the entity id; keep the in-place rename hook."""
        super().async_entity_id_changed(old_entity_id)


type EntityFactory[T] = Callable[[HarmonyNgCoordinator, T], Iterable[HarmonyNgEntity]]


@callback
def async_add_dynamic_entities[T](
    coordinator: HarmonyNgCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    keys: Callable[[HubState], Iterable[T]],
    factory: EntityFactory[T],
) -> Callable[[], None]:
    """Add entities for every key the state reports, now and as new ones appear.

    Remotes pair into a slot and Bluetooth hosts pair with the Hub at any time;
    this keeps the entity set in step without a reload. Returns the unsubscribe
    callback for the coordinator listener.
    """
    known: set[T] = set()

    @callback
    def _check() -> None:
        new_keys = [key for key in keys(coordinator.data) if key not in known]
        if not new_keys:
            return
        known.update(new_keys)
        entities = [entity for key in new_keys for entity in factory(coordinator, key)]
        if entities:
            async_add_entities(entities)

    _check()
    return coordinator.async_add_listener(_check)
