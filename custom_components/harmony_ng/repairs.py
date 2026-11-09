"""Repairs: the fix flow that removes the Hub's MQTT discovery device left behind.

With Home Assistant discovery on (the firmware default) the Hub publishes its own
MQTT discovery device, and it lives next to this integration's devices on purpose.
When discovery is turned off the Hub clears its discovery configs and the mqtt
integration removes the entities, unless Home Assistant missed that moment: then
the device stays behind. The issue is raised only while the Hub reports discovery
off, and only for the device whose discovery payload names this Hub.
"""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir

from .const import DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS

DATA_HUB_ID = "hub_id"


def discovery_identifier(hub_id: str) -> tuple[str, str]:
    """Return the identifier the Hub puts in its discovery payload's device block."""
    return ("mqtt", f"harmony-ng-{hub_id}")


@callback
def async_find_discovery_orphans(hass: HomeAssistant, hub_id: str) -> list[dr.DeviceEntry]:
    """Return the mqtt devices the Hub's discovery created."""
    # Any config entry: the device belongs to the mqtt integration's entry
    return dr.async_get(hass).async_get_devices(identifiers={discovery_identifier(hub_id)})


def _device_names(devices: list[dr.DeviceEntry]) -> str:
    return ", ".join(sorted(d.name_by_user or d.name or d.id for d in devices))


@callback
def async_refresh_discovery_issue(
    hass: HomeAssistant, entry_id: str, title: str, hub_id: str, ha_discovery: bool | None
) -> None:
    """Raise or clear the issue; never while discovery is on or its setting unknown.

    Firmware that does not report the setting (MQTT transport before firmware A4)
    leaves it None, which is not the same as off.
    """
    orphans = async_find_discovery_orphans(hass, hub_id) if ha_discovery is False else []
    with ir.async_refresh_issues(
        hass, DOMAIN, issue_ids=[ISSUE_MQTT_DISCOVERY_ORPHANS], config_entry_id=entry_id
    ):
        if orphans:
            ir.async_create_issue(
                hass,
                DOMAIN,
                ISSUE_MQTT_DISCOVERY_ORPHANS,
                config_entry_id=entry_id,
                data={DATA_HUB_ID: hub_id},
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_MQTT_DISCOVERY_ORPHANS,
                translation_placeholders={"name": title, "devices": _device_names(orphans)},
            )


class DiscoveryOrphansRepairFlow(RepairsFlow):
    """Confirm, then delete the Hub's discovery devices and their entities."""

    def __init__(self, hub_id: str) -> None:
        """Remember which Hub's devices to remove."""
        self._hub_id = hub_id

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> RepairsFlowResult:
        """Go straight to the confirmation."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Remove the orphans on confirm; Home Assistant then deletes the issue."""
        orphans = async_find_discovery_orphans(self.hass, self._hub_id)
        if user_input is not None:
            entity_registry = er.async_get(self.hass)
            device_registry = dr.async_get(self.hass)
            for device in orphans:
                for entry in er.async_entries_for_device(
                    entity_registry, device.id, include_disabled_entities=True
                ):
                    entity_registry.async_remove(entry.entity_id)
                device_registry.async_remove_device(device.id)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm", description_placeholders={"devices": _device_names(orphans)}
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix flow for a fixable issue of this integration."""
    return DiscoveryOrphansRepairFlow(str((data or {}).get(DATA_HUB_ID) or ""))
