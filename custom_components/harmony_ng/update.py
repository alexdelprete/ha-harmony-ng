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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .const import RELEASE_URL, UPDATE_CHECK_INTERVAL_HOURS
from .coordinator import HarmonyNgCoordinator
from .entity import HarmonyNgEntity
from .helpers import hub_call
from .pyharmonyng import HarmonyNgError, UpdateStatus

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=UPDATE_CHECK_INTERVAL_HOURS)
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
        self.coordinator.config_entry.async_create_background_task(
            self.hass, self._async_first_check(), "harmony_ng release check"
        )

    async def _async_first_check(self) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Ask the Hub to check for a release."""
        self._checked_version = self.installed_version
        try:
            self._status = await self.coordinator.transport.update_check()
        except HarmonyNgError as err:
            _LOGGER.debug("Release check failed: %s", err)

    async def async_install(self, version: str | None, backup: bool, **kwargs: object) -> None:
        """Install the release; the Hub restarts and reconnects on its own."""
        await hub_call(self.coordinator.transport.update_apply())

    @callback
    def _handle_coordinator_update(self) -> None:
        """Check again once the Hub comes back with a different version."""
        if self._checked_version is not None and self.installed_version != self._checked_version:
            self._checked_version = self.installed_version
            self.coordinator.config_entry.async_create_background_task(
                self.hass, self._async_first_check(), "harmony_ng release check"
            )
        super()._handle_coordinator_update()
