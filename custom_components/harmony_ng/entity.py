"""Base entity for Harmony NG."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, VERSION
from .coordinator import HarmonyNgCoordinator


class HarmonyNgEntity(CoordinatorEntity[HarmonyNgCoordinator]):
    """Base class for Harmony NG entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HarmonyNgCoordinator,
        description: EntityDescription,
        *,
        sub_device_id: str | None = None,
    ) -> None:
        """Initialize the entity and the device it belongs to.

        Without sub_device_id the entity belongs to the hub device registered in
        async_setup_entry. With one, it belongs to a device reached through the
        hub, linked with via_device_id.
        """
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        hub_identifier = (DOMAIN, coordinator.device_unique_id)

        if sub_device_id is None:
            self._attr_unique_id = f"{coordinator.device_unique_id}_{description.key}"
            self._attr_device_info = DeviceInfo(identifiers={hub_identifier})
            return

        # DeviceInfo is a keyword-only dataclass (Home Assistant 2026.11). The parent
        # is linked by registry id: look the hub up by identifier *and* entry id,
        # since identifiers are unique per config entry (async_get_device and
        # via_device, the identifier-tuple form, are deprecated and go in 2027.8).
        hub = dr.async_get(coordinator.hass).async_get_device_by_identifier(
            hub_identifier, entry.entry_id
        )
        self._attr_unique_id = f"{sub_device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sub_device_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"{entry.title} {sub_device_id}",
            sw_version=VERSION,
            via_device_id=hub.id if hub is not None else None,
        )

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Re-key anything derived from the entity id after an in-place rename.

        Since Home Assistant 2026.11 an entity whose entity_id changes is updated in
        place instead of removed and re-added; implementing this hook (even as a
        plain super() call) opts the entity in before the compatibility path ends
        in 2027.11. Update listeners or signals keyed on self.entity_id here, call
        super() first and never await.
        """
        super().async_entity_id_changed(old_entity_id)
