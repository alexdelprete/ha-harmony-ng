"""Repair flows for Harmony NG."""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant


class DeviceOfflineRepairFlow(RepairsFlow):
    """Handler for device offline repair flow."""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,
    ) -> RepairsFlowResult:
        """Handle the first step of a fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self,
        user_input: dict[str, str] | None = None,
    ) -> RepairsFlowResult:
        """Handle the confirm step; Home Assistant deletes the issue when the flow completes."""
        if user_input is not None:
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for an issue created with is_fixable=True."""
    return DeviceOfflineRepairFlow()
