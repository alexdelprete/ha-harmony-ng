"""DataUpdateCoordinator for Harmony NG."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, ISSUE_DEVICE_OFFLINE

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = 30


class HarmonyNgCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Harmony NG."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        # Stable id of the hub device (serial number, MAC, ...): the config entry's
        # unique_id when the config flow sets one, never a host or IP.
        self.device_unique_id = config_entry.unique_id or config_entry.entry_id
        self._offline_issue_id = f"{ISSUE_DEVICE_OFFLINE}_{config_entry.entry_id}"

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the device."""
        try:
            # TODO: Implement data fetching
            data: dict[str, Any] = {}
        except Exception as err:
            self._async_refresh_issues(offline=True)
            raise UpdateFailed(f"Error communicating with device: {err}") from err
        self._async_refresh_issues(offline=False)
        return data

    @callback
    def _async_refresh_issues(self, *, offline: bool) -> None:
        """Keep this entry's repair issues in step with the last update.

        Issues created with config_entry_id (Home Assistant 2026.11) are removed
        with the entry and shown on its page. async_refresh_issues deletes, on exit,
        every issue of the set that was not created or kept inside the block, so a
        recovered device loses its issue without a paired async_delete_issue, and
        an issue that stays keeps the user's ignore flag.
        """
        entry_id = self.config_entry.entry_id
        with ir.async_refresh_issues(
            self.hass, DOMAIN, issue_ids=[self._offline_issue_id], config_entry_id=entry_id
        ):
            if offline:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    self._offline_issue_id,
                    config_entry_id=entry_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_DEVICE_OFFLINE,
                    translation_placeholders={"name": self.config_entry.title},
                )
