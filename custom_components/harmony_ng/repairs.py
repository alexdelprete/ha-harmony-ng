"""Repairs: the fix flow that removes the Hub's old MQTT discovery entities.

Firmware before milestone 3 published Home Assistant discovery configs for a
handful of sensors and buttons. Once the Hub stops publishing them, their
registry entries stay behind under the mqtt integration and duplicate what this
integration provides. The issue lists them and the fix removes them.
"""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir

from .const import DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS

ORPHAN_MARKERS = ("_ir_devices", "_ir_commands")
"""Unique id suffixes that only the Hub's old discovery set used, together."""


@callback
def async_find_discovery_orphans(hass: HomeAssistant) -> list[dr.DeviceEntry]:
    """Return the mqtt devices that hold the Hub's old discovery entities."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    suffixes_by_device: dict[str, set[str]] = {}
    for entry in entity_registry.entities.values():
        if entry.platform != "mqtt" or entry.device_id is None:
            continue
        for marker in ORPHAN_MARKERS:
            if str(entry.unique_id).endswith(marker):
                suffixes_by_device.setdefault(entry.device_id, set()).add(marker)
    orphans: list[dr.DeviceEntry] = []
    for device_id, suffixes in suffixes_by_device.items():
        if suffixes != set(ORPHAN_MARKERS):
            continue
        device = device_registry.async_get(device_id)
        if isinstance(device, dr.DeviceEntry):
            orphans.append(device)
    return orphans


@callback
def async_refresh_discovery_issue(hass: HomeAssistant, entry_id: str, title: str) -> None:
    """Raise or clear the orphaned discovery entities issue for an entry."""
    orphans = async_find_discovery_orphans(hass)
    with ir.async_refresh_issues(
        hass, DOMAIN, issue_ids=[ISSUE_MQTT_DISCOVERY_ORPHANS], config_entry_id=entry_id
    ):
        if orphans:
            ir.async_create_issue(
                hass,
                DOMAIN,
                ISSUE_MQTT_DISCOVERY_ORPHANS,
                config_entry_id=entry_id,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_MQTT_DISCOVERY_ORPHANS,
                translation_placeholders={
                    "name": title,
                    "devices": ", ".join(sorted(d.name_by_user or d.name or d.id for d in orphans)),
                },
            )


class DiscoveryOrphansRepairFlow(RepairsFlow):
    """Confirm, then delete the old discovery devices and their entities."""

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> RepairsFlowResult:
        """Go straight to the confirmation."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Remove the orphans on confirm; Home Assistant then deletes the issue."""
        orphans = async_find_discovery_orphans(self.hass)
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
            step_id="confirm",
            description_placeholders={
                "devices": ", ".join(sorted(d.name_by_user or d.name or d.id for d in orphans))
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix flow for a fixable issue of this integration."""
    return DiscoveryOrphansRepairFlow()
