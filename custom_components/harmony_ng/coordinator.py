"""Coordinator: one state object fed by the transport's events."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TRANSPORT,
    DEVICE_IDENTIFIER_PREFIX,
    DOMAIN,
    ISSUE_FIRMWARE_TOO_OLD,
    ISSUE_LEGACY_ENABLED,
    MANUFACTURER,
    MODEL_HUB,
    TRANSPORT_API,
)
from .pyharmonyng import (
    Activity,
    ActivityProgressEvent,
    ActivityState,
    ActivityStateEvent,
    BtStatus,
    BtStatusEvent,
    ButtonEvent,
    ConfigChangedEvent,
    HarmonyNgAuthError,
    HarmonyNgConnectionError,
    HarmonyNgError,
    HarmonyNgUnsupportedError,
    HubEvent,
    HubStatus,
    Inventory,
    IrReceivedEvent,
    IrSignal,
    RemoteButton,
    RfSlot,
    RfStatus,
    RfStatusEvent,
    Snapshot,
)
from .transport import HarmonyNgTransport

_LOGGER = logging.getLogger(__name__)

REFETCH_COOLDOWN = 2.0
"""Seconds to coalesce inventory refetches after config changes."""

type ButtonListener = Callable[[RemoteButton], None]
type IrListener = Callable[[IrSignal], None]


DEFAULT_REMOTE_NAME = "Harmony remote"


def remote_device_name(rf: RfStatus, slot: int) -> str:
    """Name a remote after its product, with the slot when another remote shares it."""
    rf_slot = rf.slot(slot)
    product = rf_slot.product_name if rf_slot else None
    base = product or DEFAULT_REMOTE_NAME
    shared = any(
        other.slot != slot and other.active and (other.product_name or DEFAULT_REMOTE_NAME) == base
        for other in rf.slots
    )
    return f"{base} {slot}" if shared else base


@dataclass(frozen=True, slots=True)
class HubState:
    """Everything the entities read, replaced as a whole on every event."""

    hub: HubStatus
    activity: ActivityState
    activities: tuple[Activity, ...]
    inventory: Inventory
    rf: RfStatus
    bt: BtStatus
    config_files: Mapping[str, int]
    last_activity_id: str | None
    last_button: RemoteButton | None
    connected: bool
    received_at: datetime

    def activity_name(self, activity_id: str) -> str | None:
        """Return the name of an activity, or None for power off and unknown ids."""
        return next((a.name for a in self.activities if a.id == activity_id), None)

    def activity_by_name(self, name: str) -> Activity | None:
        """Return the activity with that name, case-insensitively."""
        wanted = name.casefold()
        return next((a for a in self.activities if a.name.casefold() == wanted), None)

    def activity_by_id(self, activity_id: str) -> Activity | None:
        """Return the activity with that id."""
        return next((a for a in self.activities if a.id == activity_id), None)

    def slot(self, number: int) -> RfSlot | None:
        """Return the RF slot with that number."""
        return self.rf.slot(number)

    def has(self, capability: str) -> bool:
        """Return whether the Hub lists the capability."""
        return capability in self.hub.capabilities


class HarmonyNgCoordinator(DataUpdateCoordinator[HubState]):
    """Holds the Hub state and turns transport events into updates.

    There is no polling: `update_interval` is None. The transport calls back on
    every event, on connection changes and with the snapshot of every reconnect.
    Inventory and activities are fetched at setup and again, debounced, when the
    Hub reports a configuration change or a reconnect with missed events.
    """

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, transport: HarmonyNgTransport
    ) -> None:
        """Wire the transport's callbacks to this coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=None,
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REFETCH_COOLDOWN, immediate=False
            ),
        )
        self.transport = transport
        self._state: HubState | None = None
        self._last_activity_id: str | None = None
        self._button_listeners: dict[int, list[ButtonListener]] = {}
        self._ir_listeners: list[IrListener] = []
        transport.set_callbacks(
            on_event=self._handle_event,
            on_connection=self._handle_connection,
            on_snapshot=self._handle_snapshot,
        )

    @property
    def hub_id(self) -> str:
        """Return the Hub id, the config entry's unique id."""
        unique_id = self.config_entry.unique_id
        if unique_id is None:
            raise ValueError("the config entry has no unique id")
        return unique_id

    @property
    def transport_name(self) -> str:
        """Return the configured transport."""
        return str(self.config_entry.data.get(CONF_TRANSPORT, TRANSPORT_API))

    async def _async_setup(self) -> None:
        """Connect and keep the first snapshot; activities and inventory follow."""
        try:
            snapshot = await self.transport.connect()
        except HarmonyNgAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except HarmonyNgUnsupportedError as err:
            self._async_refresh_issues(firmware_too_old=str(err))
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="firmware_too_old",
                translation_placeholders={"error": str(err)},
            ) from err
        except HarmonyNgError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        if snapshot.hub.hub_id != self.hub_id:
            await self.transport.disconnect()
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="hub_mismatch",
                translation_placeholders={"expected": self.hub_id, "found": snapshot.hub.hub_id},
            )
        self._state = self._state_from_snapshot(snapshot, (), Inventory((), None))
        self._async_refresh_issues(legacy_enabled=snapshot.hub.legacy_enabled)

    async def _async_update_data(self) -> HubState:
        """Fetch activities and inventory; everything else comes from events."""
        base = self.data or self._state
        if base is None:
            raise UpdateFailed("the coordinator was not set up")
        try:
            activities = await self.transport.fetch_activities()
            inventory = await self.transport.fetch_inventory()
        except HarmonyNgAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except HarmonyNgError as err:
            raise UpdateFailed(f"cannot read the Hub's configuration: {err}") from err
        self._state = replace(
            base, activities=activities, inventory=inventory, received_at=dt_util.utcnow()
        )
        return self._state

    async def async_shutdown(self) -> None:
        """Close the transport with the coordinator."""
        await super().async_shutdown()
        await self.transport.disconnect()

    # Devices

    def hub_device_info(self) -> DeviceInfo:
        """Return the Hub's device info."""
        hub = self._state.hub if self._state else None
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub_id)},
            manufacturer=MANUFACTURER,
            model=MODEL_HUB,
            name=self.config_entry.title,
            serial_number=self.hub_id,
            sw_version=hub.version if hub else None,
            hw_version=hub.firmware if hub and hub.firmware else None,
            configuration_url=self.configuration_url,
        )

    @property
    def configuration_url(self) -> str | None:
        """Return the Hub's web UI address for the API transport."""
        if self.transport_name != TRANSPORT_API:
            return None
        host = self.config_entry.data.get("host")
        port = self.config_entry.data.get("port", 8089)
        return f"http://{host}:{port}" if host else None

    def remote_identifier(self, slot: int) -> str:
        """Return the identifier of the remote in a slot: its unit id, else hub id and slot."""
        state = self.data or self._state
        rf_slot = state.slot(slot) if state else None
        if rf_slot is not None and rf_slot.remote_id:
            return rf_slot.remote_id
        return f"{self.hub_id}:slot{slot}"

    def remote_device_info(self, slot: int) -> DeviceInfo:
        """Return the device info of the remote in a slot, linked under the Hub."""
        state = self.data or self._state
        rf_slot = state.slot(slot) if state else None
        hub = dr.async_get(self.hass).async_get_device_by_identifier(
            (DOMAIN, self.hub_id), self.config_entry.entry_id
        )
        rf = state.rf if state else None
        product = rf_slot.product_name if rf_slot else None
        return DeviceInfo(
            identifiers={(DOMAIN, self.remote_identifier(slot))},
            manufacturer=MANUFACTURER,
            model=product,
            name=remote_device_name(rf, slot) if rf else DEFAULT_REMOTE_NAME,
            serial_number=rf_slot.remote_id if rf_slot else None,
            sw_version=rf_slot.sw_version if rf_slot else None,
            via_device_id=hub.id if hub is not None else None,
        )

    def child_identifier(self, device_id: str) -> str:
        """Return the registry identifier of a configured device's child device."""
        return f"{self.hub_id}:{DEVICE_IDENTIFIER_PREFIX}:{device_id}"

    def child_device_info(self, device_id: str) -> ChildDeviceInfo:
        """Return the child device info of a configured IR or Bluetooth device."""
        hub = dr.async_get(self.hass).async_get_device_by_identifier(
            (DOMAIN, self.hub_id), self.config_entry.entry_id
        )
        if hub is None:
            raise ValueError("the Hub device is not registered yet")
        state = self.data or self._state
        device = state.inventory.device(device_id) if state else None
        return ChildDeviceInfo(
            identifiers={(DOMAIN, self.child_identifier(device_id))},
            name=device.name if device else device_id,
            parent_device_id=hub.id,
        )

    # Pushed signals that are not state

    @callback
    def async_add_ir_listener(self, listener: IrListener) -> Callable[[], None]:
        """Subscribe to captured infrared signals; returns the unsubscribe callback."""
        self._ir_listeners.append(listener)

        @callback
        def unsubscribe() -> None:
            self._ir_listeners.remove(listener)

        return unsubscribe

    @callback
    def async_add_button_listener(self, slot: int, listener: ButtonListener) -> Callable[[], None]:
        """Subscribe to the buttons of one remote; returns the unsubscribe callback."""
        listeners = self._button_listeners.setdefault(slot, [])
        listeners.append(listener)

        @callback
        def unsubscribe() -> None:
            listeners.remove(listener)

        return unsubscribe

    # Transport callbacks

    @callback
    def _handle_event(self, event: HubEvent) -> None:
        state = self.data or self._state
        if state is None:
            return
        new_state = self._apply_event(state, event)
        if isinstance(event, RfStatusEvent):
            self._migrate_remote_identities(state.rf, new_state.rf)
            self._refresh_remote_devices(state.rf, new_state.rf)
        if isinstance(event, ButtonEvent):
            for listener in list(self._button_listeners.get(event.button.slot, ())):
                listener(event.button)
        if isinstance(event, IrReceivedEvent):
            for ir_listener in list(self._ir_listeners):
                ir_listener(event.signal)
        self._set_state(new_state)
        if isinstance(event, ConfigChangedEvent) and event.inventory_changed:
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), "harmony_ng refetch"
            )

    @callback
    def _handle_connection(self, connected: bool) -> None:
        state = self.data or self._state
        if connected or state is None:
            return
        self._state = replace(state, connected=False)
        if self.data is not None:
            self.async_set_update_error(
                HarmonyNgConnectionError("the connection to the Hub dropped")
            )

    @callback
    def _handle_snapshot(self, snapshot: Snapshot) -> None:
        state = self.data or self._state
        activities = state.activities if state else ()
        inventory = state.inventory if state else Inventory((), None)
        new_state = self._state_from_snapshot(snapshot, activities, inventory)
        if state is not None:
            self._migrate_remote_identities(state.rf, new_state.rf)
            self._refresh_remote_devices(state.rf, new_state.rf)
        self._async_refresh_issues(legacy_enabled=snapshot.hub.legacy_enabled)
        self._set_state(new_state)
        if snapshot.gap or (
            state is not None and dict(state.config_files) != dict(new_state.config_files)
        ):
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), "harmony_ng refetch"
            )

    @callback
    def _set_state(self, state: HubState) -> None:
        self._state = state
        if self.data is not None or self.last_update_success is False:
            self.async_set_updated_data(state)

    def _state_from_snapshot(
        self, snapshot: Snapshot, activities: tuple[Activity, ...], inventory: Inventory
    ) -> HubState:
        self._track_last_activity(snapshot.activity_state)
        return HubState(
            hub=snapshot.hub,
            activity=snapshot.activity_state,
            activities=activities,
            inventory=inventory,
            rf=snapshot.rf_status,
            bt=snapshot.bt_status,
            config_files=snapshot.config_files,
            last_activity_id=self._last_activity_id,
            last_button=None,
            connected=True,
            received_at=dt_util.utcnow(),
        )

    def _apply_event(self, state: HubState, event: HubEvent) -> HubState:
        now = dt_util.utcnow()
        if isinstance(event, ActivityStateEvent):
            self._track_last_activity(event.state)
            return replace(
                state,
                activity=event.state,
                last_activity_id=self._last_activity_id,
                received_at=now,
            )
        if isinstance(event, ActivityProgressEvent):
            return replace(state, received_at=now)
        if isinstance(event, ConfigChangedEvent):
            return replace(state, received_at=now)
        if isinstance(event, BtStatusEvent):
            return replace(state, bt=event.status, received_at=now)
        if isinstance(event, RfStatusEvent):
            return replace(state, rf=event.status, received_at=now)
        if isinstance(event, ButtonEvent):
            return replace(state, last_button=event.button, received_at=now)
        return state

    def _track_last_activity(self, activity: ActivityState) -> None:
        if activity.is_on:
            self._last_activity_id = activity.activity_id

    # Remote identity migration

    @callback
    def _migrate_remote_identities(self, old: RfStatus, new: RfStatus) -> None:
        """Re-key a remote's device and entities when its unit id first arrives.

        Entities created for a remote without a reported unit id are keyed by Hub
        id and slot. When the id arrives, the registry entries are updated so the
        remote keeps its device, history and automations, and the entry reloads so
        the live entities pick up the new keys.
        """
        migrated = False
        for new_slot in new.slots:
            if not new_slot.remote_id:
                continue
            old_slot = old.slot(new_slot.slot)
            if old_slot is not None and old_slot.remote_id == new_slot.remote_id:
                continue
            if self._migrate_slot(new_slot.slot, new_slot.remote_id):
                migrated = True
        if migrated:
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    def _refresh_remote_devices(self, old: RfStatus, new: RfStatus) -> None:
        """Update a remote's model and name when the Hub learns its product.

        The device info only applies when entities are added, so a product that
        arrives later (a firmware update, a remote reporting its skin id) is
        written to the registry here. A name the user set stays in front.
        """
        device_registry = dr.async_get(self.hass)
        for new_slot in new.slots:
            if not new_slot.active:
                continue
            name = remote_device_name(new, new_slot.slot)
            old_slot = old.slot(new_slot.slot)
            if (
                old_slot is not None
                and old_slot.product_name == new_slot.product_name
                and remote_device_name(old, new_slot.slot) == name
            ):
                continue
            identifier = new_slot.remote_id or f"{self.hub_id}:slot{new_slot.slot}"
            device = device_registry.async_get_device_by_identifier(
                (DOMAIN, identifier), self.config_entry.entry_id
            )
            if device is None:
                continue
            if device.model != new_slot.product_name or device.name != name:
                device_registry.async_update_device(
                    device.id, model=new_slot.product_name, name=name
                )

    def _migrate_slot(self, slot: int, remote_id: str) -> bool:
        old_identifier = f"{self.hub_id}:slot{slot}"
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, old_identifier), self.config_entry.entry_id
        )
        if device is None:
            return False
        device_registry.async_update_device(
            device.id, new_identifiers={(DOMAIN, remote_id)}, serial_number=remote_id
        )
        entity_registry = er.async_get(self.hass)
        for entry in er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        ):
            if isinstance(entry.unique_id, str) and entry.unique_id.startswith(old_identifier):
                entity_registry.async_update_entity(
                    entry.entity_id,
                    new_unique_id=remote_id + entry.unique_id[len(old_identifier) :],
                )
        _LOGGER.info("Remote in slot %s now identified by its unit id", slot)
        return True

    # Repairs

    @callback
    def _async_refresh_issues(
        self, *, firmware_too_old: str | None = None, legacy_enabled: bool = False
    ) -> None:
        """Keep this entry's repair issues in step with what the Hub reports."""
        entry_id = self.config_entry.entry_id
        issue_ids = [ISSUE_FIRMWARE_TOO_OLD, ISSUE_LEGACY_ENABLED]
        with ir.async_refresh_issues(
            self.hass, DOMAIN, issue_ids=issue_ids, config_entry_id=entry_id
        ):
            if firmware_too_old is not None:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    ISSUE_FIRMWARE_TOO_OLD,
                    config_entry_id=entry_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key=ISSUE_FIRMWARE_TOO_OLD,
                    translation_placeholders={
                        "name": self.config_entry.title,
                        "error": firmware_too_old,
                    },
                )
            if legacy_enabled:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    ISSUE_LEGACY_ENABLED,
                    config_entry_id=entry_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_LEGACY_ENABLED,
                    translation_placeholders={"name": self.config_entry.title},
                )
