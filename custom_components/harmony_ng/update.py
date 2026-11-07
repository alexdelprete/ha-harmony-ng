"""Update entity: the Hub's harmony-ng firmware."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import HarmonyNgConfigEntry
from .const import RELEASE_URL, UPDATE_CHECK_INTERVAL_HOURS
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity
from .helpers import hub_call
from .pyharmonyng import HarmonyNgError, UpdateStatus

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=UPDATE_CHECK_INTERVAL_HOURS)
# A failed check (often right after the Hub boots, before it reaches the internet) is
# retried after this, instead of waiting for the next daily check
RETRY_AFTER = timedelta(minutes=15)
PARALLEL_UPDATES = 1

FIRMWARE_DESCRIPTION = UpdateEntityDescription(
    key="firmware_update",
    device_class=UpdateDeviceClass.FIRMWARE,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the firmware update entity."""
    async_add_entities([HarmonyNgFirmwareUpdate(entry.runtime_data.coordinator)])


class HarmonyNgFirmwareUpdate(HarmonyNgEntity, UpdateEntity):
    """The Hub's harmony-ng release, checked once a day and installable from here.

    The installed version comes from the coordinator's state. The latest version
    comes from the Hub's own release check, which this entity polls, since the
    Hub does not push it.
    """

    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_title = "harmony-ng"
    _attr_release_url = RELEASE_URL

    def __init__(self, coordinator: HarmonyNgCoordinator) -> None:
        """Create the update entity of the Hub."""
        super().__init__(coordinator, FIRMWARE_DESCRIPTION)
        self._status: UpdateStatus | None = None
        self._checked_version: str | None = None
        self._failing = False
        self._was_available = True
        self._retry_unsub: CALLBACK_TYPE | None = None

    @property
    def should_poll(self) -> bool:
        """Poll the Hub's release check; everything else arrives by push."""
        return True

    @property
    def installed_version(self) -> str | None:
        """Return the running firmware version."""
        return self.state_data.hub.version or None

    @property
    def latest_version(self) -> str | None:
        """Return the newest release the Hub knows about."""
        if self._status is None:
            return None
        if self._status.latest_version:
            return self._status.latest_version
        # No version string: up to date means "same as installed", otherwise unknown.
        return None if self._status.update_available else self.installed_version

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the Hub's own message about the check."""
        return {"message": self._status.message} if self._status else {}

    async def async_added_to_hass(self) -> None:
        """Run the first release check without holding the platform setup."""
        await super().async_added_to_hass()
        self._start_check()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel a pending retry."""
        self._cancel_retry()
        await super().async_will_remove_from_hass()

    async def _async_first_check(self) -> None:
        await self.async_update()
        self.async_write_ha_state()

    def _start_check(self) -> None:
        self.coordinator.config_entry.async_create_background_task(
            self.hass, self._async_first_check(), "harmony_ng release check"
        )

    async def async_update(self) -> None:
        """Ask the Hub to check for a release; retry soon when the check fails."""
        self._checked_version = self.installed_version
        try:
            status = await self.coordinator.transport.update_check()
        except HarmonyNgError as err:
            if not self._failing:
                _LOGGER.info("The Hub's release check failed, retrying in %s: %s", RETRY_AFTER, err)
            self._failing = True
            self._schedule_retry()
            return
        if self._failing:
            _LOGGER.info("The Hub's release check works again")
        self._failing = False
        self._cancel_retry()
        self._status = status

    def _schedule_retry(self) -> None:
        self._cancel_retry()
        self._retry_unsub = async_call_later(self.hass, RETRY_AFTER, self._async_retry)

    @callback
    def _async_retry(self, _now: object) -> None:
        self._retry_unsub = None
        self._start_check()

    def _cancel_retry(self) -> None:
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    async def async_install(self, version: str | None, backup: bool, **kwargs: object) -> None:
        """Install the release; the Hub restarts and reconnects on its own."""
        await hub_call(self.coordinator.transport.update_apply())

    @callback
    def _handle_coordinator_update(self) -> None:
        """Check again when the Hub comes back, or runs a different version."""
        available = self.available
        came_back = available and not self._was_available
        self._was_available = available
        version_changed = (
            self._checked_version is not None and self.installed_version != self._checked_version
        )
        if available and (came_back or version_changed):
            self._checked_version = self.installed_version
            self._start_check()
        super()._handle_coordinator_update()
