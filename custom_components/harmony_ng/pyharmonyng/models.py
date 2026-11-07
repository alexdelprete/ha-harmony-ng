"""Typed models of what the Hub reports.

Every model is a frozen dataclass with a `from_json` constructor. Unknown keys are
ignored and missing optional keys fall back to a default, so a reply from a newer
or older firmware never raises while being parsed. The one exception is the hub
status, which refuses a firmware older than the API this library speaks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from .capabilities import MIN_API_VERSION
from .exceptions import HarmonyNgUnsupportedError

type JsonDict = Mapping[str, Any]

POWER_OFF_ACTIVITY_ID = "-1"
"""Activity id the Hub reports while no activity runs."""

IR_PORT_FRONT = 1
IR_PORT_JACK1 = 2
IR_PORT_JACK2 = 4
IR_PORT_ALL = 7


class ActivityStatus(StrEnum):
    """Orchestrator state, as the Hub numbers it."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"

    @classmethod
    def from_code(cls, code: int) -> ActivityStatus:
        """Map the Hub's numeric state to the enum, idle for anything unknown."""
        try:
            return _STATUS_BY_CODE[code]
        except KeyError:
            return cls.IDLE


_STATUS_BY_CODE = {
    0: ActivityStatus.IDLE,
    1: ActivityStatus.STARTING,
    2: ActivityStatus.RUNNING,
    3: ActivityStatus.STOPPING,
}


class CommandAction(StrEnum):
    """How a device command is sent."""

    TAP = "tap"
    PRESS = "press"
    HOLD = "hold"
    RELEASE = "release"


class KeyAction(StrEnum):
    """How a Bluetooth HID key is sent."""

    TAP = "tap"
    DOWN = "down"
    UP = "up"
    RELEASE_ALL = "release_all"


def _str(data: JsonDict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return default


def _opt_str(data: JsonDict, *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _int(data: JsonDict, *keys: str, default: int = 0) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int | float):
            return int(value)
        if isinstance(value, str) and value.lstrip("-").isdigit():
            return int(value)
    return default


def _opt_int(data: JsonDict, *keys: str) -> int | None:
    for key in keys:
        if data.get(key) is not None:
            return _int(data, key)
    return None


def _opt_epoch(data: JsonDict, key: str) -> datetime | None:
    """A Unix time in seconds; None when missing, null or not positive."""
    value = _opt_int(data, key)
    return datetime.fromtimestamp(value, tz=UTC) if value and value > 0 else None


def _bool(data: JsonDict, *keys: str, default: bool = False) -> bool:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return bool(value)
    return default


def _list(data: JsonDict, *keys: str) -> list[Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _dict(data: JsonDict, key: str) -> JsonDict:
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class MqttInfo:
    """The Hub's MQTT client settings as `GET /api/status` reports them."""

    connected: bool
    broker: str
    port: int
    base_topic: str

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from the `mqtt` member of the status reply."""
        return cls(
            connected=_bool(data, "connected"),
            broker=_str(data, "broker", "host"),
            port=_int(data, "port", default=1883),
            base_topic=_str(data, "baseTopic", "base_topic"),
        )


@dataclass(frozen=True, slots=True)
class HubStatus:
    """Identity, version and capabilities of the Hub."""

    hub_id: str
    hub_name: str
    version: str
    commit: str
    api_version: int
    capabilities: frozenset[str]
    auth_enabled: bool
    uptime_sec: int | None
    legacy_enabled: bool
    mdns_enabled: bool
    firmware: str
    mqtt: MqttInfo | None
    boot_time: datetime | None = None

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from `GET /api/status` or the `hub` member of a snapshot.

        Raises:
            HarmonyNgUnsupportedError: the reply has no `hub_id` or an `api_version`
                below the one this library speaks, which means a firmware before
                milestone 1.
        """
        hub_id = _opt_str(data, "hub_id")
        if hub_id is None:
            raise HarmonyNgUnsupportedError("the Hub reports no hub_id; a newer firmware is needed")
        api_version = _int(data, "api_version")
        if api_version < MIN_API_VERSION:
            raise HarmonyNgUnsupportedError(
                f"API version {api_version} is below the required {MIN_API_VERSION}"
            )
        mqtt = data.get("mqtt")
        return cls(
            hub_id=hub_id,
            hub_name=_str(data, "hub_name", default="Harmony Hub"),
            version=_str(data, "version"),
            commit=_str(data, "commit"),
            api_version=api_version,
            capabilities=frozenset(str(flag) for flag in _list(data, "capabilities")),
            auth_enabled=_bool(data, "auth_enabled"),
            uptime_sec=_opt_int(data, "uptime_sec"),
            legacy_enabled=_bool(data, "legacy_enabled"),
            mdns_enabled=_bool(data, "mdns_enabled"),
            firmware=_str(data, "firmware"),
            mqtt=MqttInfo.from_json(mqtt) if isinstance(mqtt, Mapping) else None,
            boot_time=_opt_epoch(data, "boot_time"),
        )

    def has(self, capability: str) -> bool:
        """Return whether the Hub lists the capability."""
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class ActivityState:
    """Current activity and orchestrator state."""

    activity_id: str
    state: ActivityStatus
    busy: bool
    sending: bool

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from `GET /api/activity`, an `activity_state` event or a snapshot."""
        return cls(
            activity_id=_str(data, "activity", "activityId", default=POWER_OFF_ACTIVITY_ID),
            state=ActivityStatus.from_code(_int(data, "state")),
            busy=_bool(data, "busy"),
            sending=_bool(data, "sending"),
        )

    @property
    def is_on(self) -> bool:
        """Return whether an activity is selected, starting or running."""
        return self.activity_id != POWER_OFF_ACTIVITY_ID


@dataclass(frozen=True, slots=True)
class ActivityProgress:
    """One step of an activity start or stop sequence."""

    activity_id: str
    state: ActivityStatus
    step: int
    total: int
    description: str

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from an `activity_progress` event."""
        return cls(
            activity_id=_str(data, "activity", "activityId", default=POWER_OFF_ACTIVITY_ID),
            state=ActivityStatus.from_code(_int(data, "stateCode")),
            step=_int(data, "step", "currentStep"),
            total=_int(data, "total", "totalSteps"),
            description=_str(data, "desc", "stepDesc"),
        )


@dataclass(frozen=True, slots=True)
class Activity:
    """A configured activity."""

    id: str
    name: str
    type: str
    order: int

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from one item of `GET /api/activities` or the MQTT inventory index."""
        return cls(
            id=_str(data, "id"),
            name=_str(data, "name", "label"),
            # The MQTT index names it activityType: "type" is the message type there
            type=_str(data, "activityType", "type"),
            order=_int(data, "order"),
        )


@dataclass(frozen=True, slots=True)
class Device:
    """A configured device with the names of its commands."""

    id: str
    name: str
    type: str
    manufacturer: str
    model: str
    control_port: int
    commands: tuple[str, ...]

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from one item of `GET /api/inventory` or an MQTT device chunk.

        The REST inventory lists commands as objects with the raw code; only the
        name is kept. MQTT chunks list the names directly.
        """
        names: list[str] = []
        for item in _list(data, "commands"):
            if isinstance(item, Mapping):
                name = _opt_str(item, "name")
                if name is not None:
                    names.append(name)
            elif isinstance(item, str):
                names.append(item)
        return cls(
            id=_str(data, "id"),
            name=_str(data, "name", "label"),
            # MQTT device chunks name it deviceType: "type" is the message type there
            type=_str(data, "deviceType", "type"),
            manufacturer=_str(data, "manufacturer"),
            model=_str(data, "model"),
            control_port=_int(data, "controlPort", "control_port"),
            commands=tuple(names),
        )

    def has_command(self, command: str) -> bool:
        """Return whether the device knows the command, case-insensitively."""
        wanted = command.casefold()
        return any(name.casefold() == wanted for name in self.commands)


@dataclass(frozen=True, slots=True)
class Inventory:
    """Every configured device."""

    devices: tuple[Device, ...]
    version: str | None

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from `GET /api/inventory`; `version` only exists on the MQTT index."""
        return cls(
            devices=tuple(
                Device.from_json(item)
                for item in _list(data, "devices")
                if isinstance(item, Mapping)
            ),
            version=_opt_str(data, "inventory_version"),
        )

    def device(self, device_id: str) -> Device | None:
        """Return the device with that id, or None."""
        return next((device for device in self.devices if device.id == device_id), None)

    def device_by_name(self, name: str) -> Device | None:
        """Return the device with that name, case-insensitively, or None."""
        wanted = name.casefold()
        return next((device for device in self.devices if device.name.casefold() == wanted), None)


# Screenless remotes run stock firmware; the Hub identifies them by EquadID, reliably.
SCREENLESS_PRODUCT_NAMES: dict[str, str] = {
    "companion": "Harmony Companion",
    "smart_control": "Harmony Smart Control",
}


@dataclass(frozen=True, slots=True)
class RfSlot:
    """One RF remote slot of the Hub."""

    slot: int
    active: bool
    remote_id: str | None
    model: str
    model_name: str | None
    skin: int | None
    equad_id: int | None
    has_screen: bool
    battery_percent: int | None
    charging: bool | None
    voltage_mv: int | None
    config_version: int | None
    hub_config_version: int | None
    in_sync: bool | None
    sw_version: str | None
    last_seen_s: int | None
    battery_reported_at: datetime | None = None
    battery_restored: bool = False

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from one item of `slots` in the RF status."""
        battery = _dict(data, "battery")
        link = _dict(data, "link")
        # The Hub reports 0 % at 0 mV until the remote has sent a battery report:
        # no reading yet, not an empty battery. Newer firmware says so with a null
        # reported_at.
        never_reported = "reported_at" in battery and battery["reported_at"] is None
        if never_reported or (
            not _opt_int(battery, "percent") and not _opt_int(battery, "voltage_mv")
        ):
            battery = {}
        return cls(
            slot=_int(data, "slot"),
            active=_bool(data, "active"),
            remote_id=_opt_str(data, "remote_id"),
            model=_str(data, "model"),
            model_name=_opt_str(data, "model_name"),
            skin=_opt_int(data, "skin"),
            equad_id=_opt_int(data, "equad_id"),
            has_screen=_bool(data, "has_screen"),
            battery_percent=_opt_int(battery, "percent"),
            charging=bool(battery["charging"]) if battery.get("charging") is not None else None,
            voltage_mv=_opt_int(battery, "voltage_mv"),
            config_version=_opt_int(data, "config_version"),
            hub_config_version=_opt_int(data, "hub_config_version"),
            in_sync=bool(data["in_sync"]) if data.get("in_sync") is not None else None,
            sw_version=_opt_str(data, "sw_version", "version", "firmware"),
            last_seen_s=_opt_int(link, "last_seen_s"),
            battery_reported_at=_opt_epoch(battery, "reported_at"),
            battery_restored=_bool(battery, "restored"),
        )

    @property
    def product_name(self) -> str | None:
        """Return the remote's product name when the Hub knows it for certain.

        Firmware that reads the remote's skin id reports `model_name`. Older
        firmware reports `elite` for every touchscreen remote, a guess that also
        covers the Ultimate family, so only the screenless models it identifies by
        EquadID are named without `model_name`.
        """
        return self.model_name or SCREENLESS_PRODUCT_NAMES.get(self.model)


@dataclass(frozen=True, slots=True)
class RfStatus:
    """State of the RF subsystem and its paired remotes."""

    running: bool
    connected: bool
    pairing_active: bool
    paired: bool
    slots: tuple[RfSlot, ...]

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from `GET /api/rf/status`, an `rf_status` event or a snapshot."""
        return cls(
            running=_bool(data, "running"),
            connected=_bool(data, "connected"),
            pairing_active=_bool(data, "pairing_active"),
            paired=_bool(data, "paired"),
            slots=tuple(
                RfSlot.from_json(item) for item in _list(data, "slots") if isinstance(item, Mapping)
            ),
        )

    @property
    def active_slots(self) -> tuple[RfSlot, ...]:
        """Return the slots with a paired remote."""
        return tuple(slot for slot in self.slots if slot.active)

    def slot(self, number: int) -> RfSlot | None:
        """Return the slot with that number, or None."""
        return next((slot for slot in self.slots if slot.slot == number), None)


@dataclass(frozen=True, slots=True)
class BtHost:
    """A paired Bluetooth host."""

    bdaddr: str
    name: str
    connected: bool


@dataclass(frozen=True, slots=True)
class BtStatus:
    """State of the Bluetooth stack and its paired hosts."""

    running: bool
    connected: bool
    target: str | None
    hosts: tuple[BtHost, ...]

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from `GET /api/bt-status`, a `bt_status` event or a snapshot.

        The Bluetooth daemon writes its status file with a `pid`, the active host
        under `host` and every host under `hosts`, each with `addr` and a
        `connected` flag of its own; its top-level `target` is the physical
        remote's address. It writes no top-level `running` or `connected`. The
        shape the API document describes has those two, `target` as the host and
        hosts without a flag, where a host counts as connected when the stack
        reports a connection and the host is the target.
        """
        active = data.get("host")
        active_host: Mapping[str, Any] = active if isinstance(active, Mapping) else {}
        items = [item for item in _list(data, "hosts", "devices") if isinstance(item, Mapping)]
        if "connected" in data:
            connected = _bool(data, "connected")
        elif "connected" in active_host:
            connected = _bool(active_host, "connected")
        else:
            connected = any(_bool(item, "connected") for item in items)
        if active_host:
            target = _opt_str(active_host, "addr") if connected else None
        else:
            target = _opt_str(data, "target")
        target_key = target.casefold() if target else None
        hosts: list[BtHost] = []
        for item in items:
            address = _str(item, "addr", "bdaddr")
            # A top-level flag, where there is one, still overrides the host's own
            host_connected = connected and (
                _bool(item, "connected")
                if item.get("connected") is not None
                else address.casefold() == target_key
            )
            hosts.append(BtHost(bdaddr=address, name=_str(item, "name"), connected=host_connected))
        running = _bool(data, "running") if "running" in data else _int(data, "pid") > 0
        return cls(running=running, connected=connected, target=target, hosts=tuple(hosts))


@dataclass(frozen=True, slots=True)
class RemoteButton:
    """A physical key pressed or released on an RF remote."""

    slot: int
    button: str
    action: str
    device_id: str | None
    command: str | None
    source: str

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from a `button` event."""
        return cls(
            slot=_int(data, "slot", default=1),
            button=_str(data, "button", "command"),
            action=_str(data, "action", default="press"),
            device_id=_opt_str(data, "deviceId", "device_id"),
            command=_opt_str(data, "command"),
            source=_str(data, "source"),
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything the Hub knows, sent after a WebSocket connect."""

    hub: HubStatus
    activity_state: ActivityState
    bt_status: BtStatus
    rf_status: RfStatus
    config_files: Mapping[str, int]
    seq: int
    gap: bool = False
    """True when events were missed since the previous connection."""

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from a `snapshot` frame."""
        files = _dict(_dict(data, "config"), "files")
        return cls(
            hub=HubStatus.from_json(_dict(data, "hub")),
            activity_state=ActivityState.from_json(_dict(data, "activity_state")),
            bt_status=BtStatus.from_json(_dict(data, "bt_status")),
            rf_status=RfStatus.from_json(_dict(data, "rf_status")),
            config_files={str(key): _int(files, key) for key in files},
            seq=_int(data, "seq"),
        )

    def with_gap(self, gap: bool) -> Snapshot:
        """Return a copy with the gap flag set."""
        return replace(self, gap=gap)


@dataclass(frozen=True, slots=True)
class HelpDevice:
    """A device whose power is a toggle, listed by the Help feature."""

    id: str
    name: str
    command: str


@dataclass(frozen=True, slots=True)
class HelpResult:
    """What the Help feature re-sent and which devices it asks about."""

    activity_id: str
    toggle_devices: tuple[HelpDevice, ...]

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from the reply of `POST /api/activity/help`."""
        return cls(
            activity_id=_str(data, "activity", default=POWER_OFF_ACTIVITY_ID),
            toggle_devices=tuple(
                HelpDevice(
                    id=_str(item, "id"), name=_str(item, "name"), command=_str(item, "command")
                )
                for item in _list(data, "toggleDevices")
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    """Firmware versions as the Hub's update endpoints report them."""

    current_version: str
    latest_version: str | None
    update_available: bool
    message: str

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from `GET /api/update-status` or the reply of `/api/update-check`."""
        latest = _opt_str(data, "remote_version", "latest_version")
        return cls(
            current_version=_str(data, "current_version", "version").lstrip("vV"),
            latest_version=latest.lstrip("vV") if latest else None,
            update_available=_bool(data, "update_available", "has_update"),
            message=_str(data, "message"),
        )


@dataclass(frozen=True, slots=True)
class IrSignal:
    """An infrared signal the Hub captured: signed timings and the carrier."""

    timings: tuple[int, ...]
    modulation: int | None

    @classmethod
    def from_json(cls, data: JsonDict) -> Self:
        """Build from an `ir_received` event."""
        timings = tuple(int(v) for v in _list(data, "timings") if isinstance(v, int | float))
        return cls(timings=timings, modulation=_opt_int(data, "modulation", "frequency"))
