"""Base entity for Harmony NG."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
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
        # The remote this entity belongs to; another remote in the slot gets entities of its own
        self._remote = owner if slot is not None else None
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
        """Unavailable while the Hub is unreachable, or while the slot holds no remote or another."""
        if not super().available or not self.coordinator.data.connected:
            return False
        if self._slot is None:
            return True
        rf_slot = self.coordinator.data.slot(self._slot)
        return (
            rf_slot is not None
            and rf_slot.active
            and self.coordinator.remote_identifier(self._slot) == self._remote
        )

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Nothing here is keyed on the entity id; keep the in-place rename hook."""
        super().async_entity_id_changed(old_entity_id)


type EntityFactory[T] = Callable[[HarmonyNgCoordinator, T], Iterable[HarmonyNgEntity]]
type RemoteEntityFactory = Callable[[HarmonyNgCoordinator, int], Iterable[HarmonyNgEntity]]


@callback
def async_add_dynamic_entities[T](
    coordinator: HarmonyNgCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    keys: Callable[[HubState], Iterable[T]],
    factory: EntityFactory[T],
) -> Callable[[], None]:
    """Add entities for every key the state reports, now and as new ones appear.

    Remotes pair into a slot, Bluetooth hosts pair with the Hub and devices are
    configured at any time; this keeps the entity set in step without a reload.
    The coordinator removes what the Hub no longer reports; a key whose entities
    are gone from the registry is forgotten, so it gets new entities if it comes
    back. Returns the unsubscribe callback for the coordinator listener.
    """
    known: dict[T, list[HarmonyNgEntity]] = {}
    entity_registry = er.async_get(coordinator.hass)

    def _gone(entities: list[HarmonyNgEntity]) -> bool:
        # An entity not added yet has no entity id: it is not gone
        return all(
            entity.entity_id is not None
            and not entity_registry.async_is_registered(entity.entity_id)
            for entity in entities
        )

    @callback
    def _check() -> None:
        if coordinator.reload_pending:
            # Remotes are being re-keyed; the reload creates the entities
            return
        current = list(dict.fromkeys(keys(coordinator.data)))
        for key in [key for key in known if key not in current and _gone(known[key])]:
            del known[key]
        new_keys = [key for key in current if key not in known]
        if not new_keys:
            return
        entities: list[HarmonyNgEntity] = []
        for key in new_keys:
            known[key] = list(factory(coordinator, key))
            entities.extend(known[key])
        if entities:
            async_add_entities(entities)

    _check()
    return coordinator.async_add_listener(_check)


@callback
def async_add_remote_entities(
    coordinator: HarmonyNgCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: RemoteEntityFactory,
) -> Callable[[], None]:
    """Add the entities of every paired remote, keyed by the remote, not by its slot.

    A remote is its unit id, or the Hub id and slot while the Hub has none yet, so a
    remote swapped into a slot gets a device and entities of its own at once.
    """

    def _create(coord: HarmonyNgCoordinator, remote: str) -> Iterable[HarmonyNgEntity]:
        slot = coord.remote_identities(coord.data).get(remote)
        return factory(coord, slot) if slot is not None else ()

    return async_add_dynamic_entities(
        coordinator,
        async_add_entities,
        coordinator.remote_identities,
        _create,
    )
