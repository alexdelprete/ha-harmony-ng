"""The MQTT transport: retained state topics and a command channel, through the HA MQTT integration.

The Hub publishes the same JSON objects it sends over the WebSocket, so the
library's event parser serves both transports and the coordinator cannot tell
them apart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
import json
import logging
from typing import Any, Final
from uuid import uuid4

from custom_components.harmony_ng.pyharmonyng import (
    CAP_MQTT_V2,
    UPDATE_CHECK_TIMEOUT,
    Activity,
    ActivityState,
    BtStatus,
    CommandAction,
    ConfigChangedEvent,
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
    HarmonyNgUnsupportedError,
    HelpResult,
    HubStatus,
    Inventory,
    KeyAction,
    RfStatus,
    Snapshot,
    UpdateStatus,
    parse,
)
from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from . import ConnectionCallback, EventCallback, SnapshotCallback

_LOGGER = logging.getLogger(__name__)

TRANSPORT_NAME = "mqtt"
CONNECT_TIMEOUT: Final = 10.0
COMMAND_TIMEOUT: Final = 10.0
INVENTORY_TIMEOUT: Final = 10.0

TOPIC_STATUS: Final = "status"
TOPIC_HUB: Final = "hub"
TOPIC_ACTIVITY_STATE: Final = "activity_state"
TOPIC_PROGRESS: Final = "progress"
TOPIC_BT: Final = "bt"
TOPIC_RF: Final = "rf"
TOPIC_CONFIG: Final = "config"
TOPIC_INVENTORY_INDEX: Final = "inventory/index"
TOPIC_INVENTORY_DEVICE: Final = "inventory/+"
TOPIC_BUTTON: Final = "remote/+/button"
TOPIC_CMD: Final = "cmd"
TOPIC_CMD_RESPONSE: Final = "cmd/response"
TOPIC_IR_RAW: Final = "ir/raw"
TOPIC_IR_RECEIVED: Final = "ir/received"

STATE_TOPICS: Final = (TOPIC_HUB, TOPIC_ACTIVITY_STATE, TOPIC_BT, TOPIC_RF)
EVENT_TOPICS: Final = (TOPIC_ACTIVITY_STATE, TOPIC_PROGRESS, TOPIC_BT, TOPIC_RF, TOPIC_BUTTON)


class MqttTransport:
    """Subscribes to the Hub's retained state and publishes commands with a correlation id."""

    name = TRANSPORT_NAME

    def __init__(self, hass: HomeAssistant, base_topic: str) -> None:
        """Keep the base topic; nothing is subscribed until `connect`."""
        self._hass = hass
        self._base = base_topic.rstrip("/")
        self._unsubscribe: list[Callable[[], None]] = []
        self._retained: dict[str, Mapping[str, Any]] = {}
        self._retained_events: dict[str, asyncio.Event] = {
            topic: asyncio.Event() for topic in STATE_TOPICS
        }
        self._index: Mapping[str, Any] | None = None
        self._chunks: dict[str, Mapping[str, Any]] = {}
        self._inventory_changed = asyncio.Event()
        self._inventory_version: str | None = None
        self._pending: dict[str, asyncio.Future[Mapping[str, Any]]] = {}
        self._hub_online = False
        self._ready = False
        self._status: HubStatus | None = None
        self._on_event: EventCallback | None = None
        self._on_connection: ConnectionCallback | None = None
        self._on_snapshot: SnapshotCallback | None = None

    @property
    def base_topic(self) -> str:
        """Return the Hub's base topic."""
        return self._base

    @property
    def hub_id(self) -> str | None:
        """Return the Hub id from the retained hub topic."""
        return self._status.hub_id if self._status else None

    @property
    def capabilities(self) -> frozenset[str]:
        """Return the capability flags from the retained hub topic."""
        return self._status.capabilities if self._status else frozenset()

    @property
    def connected(self) -> bool:
        """Return whether the Hub reports itself online through the broker."""
        return self._ready and self._hub_online

    def status_version(self) -> str | None:
        """Return the firmware version from the latest retained hub topic."""
        return self._status.version if self._status else None

    def set_callbacks(
        self,
        *,
        on_event: EventCallback,
        on_connection: ConnectionCallback,
        on_snapshot: SnapshotCallback,
    ) -> None:
        """Register the coordinator's callbacks."""
        self._on_event = on_event
        self._on_connection = on_connection
        self._on_snapshot = on_snapshot

    def set_token(self, token: str | None) -> None:
        """Credentials are the broker's; nothing to do."""

    async def connect(self) -> Snapshot:
        """Subscribe and build the first snapshot from the retained topics.

        Raises:
            HarmonyNgConnectionError: the MQTT integration is not available, the
                Hub's retained state does not arrive, or the Hub reports offline.
            HarmonyNgUnsupportedError: the Hub's MQTT layer predates milestone 3.
        """
        if self._on_event is None or self._on_connection is None or self._on_snapshot is None:
            raise RuntimeError("set_callbacks must be called before connect")
        if not await mqtt.async_wait_for_mqtt_client(self._hass):
            raise HarmonyNgConnectionError("the MQTT integration is not available")
        await self._subscribe_all()
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                for event in self._retained_events.values():
                    await event.wait()
        except TimeoutError as err:
            await self.disconnect()
            missing = [t for t, e in self._retained_events.items() if not e.is_set()]
            raise HarmonyNgConnectionError(
                f"no retained state on {self._base}/{', '.join(missing)}"
            ) from err
        try:
            status = HubStatus.from_json(self._retained[TOPIC_HUB])
        except HarmonyNgUnsupportedError:
            await self.disconnect()
            raise
        if not status.has(CAP_MQTT_V2):
            await self.disconnect()
            raise HarmonyNgUnsupportedError("the Hub's MQTT layer lacks mqtt_v2")
        if not self._hub_online:
            await self.disconnect()
            raise HarmonyNgConnectionError("the Hub reports offline on the broker")
        self._status = status
        self._ready = True
        return self._build_snapshot()

    async def disconnect(self) -> None:
        """Unsubscribe from everything."""
        self._ready = False
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(HarmonyNgConnectionError("the transport was closed"))
        self._pending.clear()

    async def fetch_inventory(self) -> Inventory:
        """Assemble the inventory from the index and one chunk per device."""
        try:
            async with asyncio.timeout(INVENTORY_TIMEOUT):
                while not self._inventory_complete():
                    self._inventory_changed.clear()
                    await self._inventory_changed.wait()
        except TimeoutError as err:
            raise HarmonyNgConnectionError("the retained inventory is incomplete") from err
        index = self._index or {}
        version = str(index.get("inventory_version") or "") or None
        devices = tuple(
            Inventory.from_json({"devices": [self._chunks[str(item["id"])]]}).devices[0]
            for item in index.get("devices", [])
            if isinstance(item, Mapping) and str(item.get("id")) in self._chunks
        )
        return Inventory(devices=devices, version=version)

    async def fetch_activities(self) -> tuple[Activity, ...]:
        """Return the activities listed by the retained index."""
        try:
            async with asyncio.timeout(INVENTORY_TIMEOUT):
                while self._index is None:
                    self._inventory_changed.clear()
                    await self._inventory_changed.wait()
        except TimeoutError as err:
            raise HarmonyNgConnectionError("the retained inventory index is missing") from err
        return tuple(
            Activity.from_json(item)
            for item in self._index.get("activities", [])
            if isinstance(item, Mapping)
        )

    async def start_activity(self, activity_id: str) -> None:
        """Start an activity."""
        await self._command("start_activity", activity=activity_id)

    async def power_off(self) -> None:
        """Stop the running activity."""
        await self._command("stop_activity")

    async def cancel_activity(self) -> None:
        """Clear a stuck activity change."""
        await self._command("cancel_activity")

    async def send_command(
        self, device_id: str, command: str, action: CommandAction, repeats: int
    ) -> None:
        """Send a device command."""
        fields: dict[str, Any] = {"deviceId": device_id, "command": command, "repeats": repeats}
        if action is not CommandAction.TAP:
            fields["status"] = action.value
        await self._command("send_command", **fields)

    async def ir_send(self, device_id: str, command: str, port: int, repeats: int) -> None:
        """Send a device command on given outputs."""
        await self._command(
            "send_command", deviceId=device_id, command=command, port=port, repeats=repeats
        )

    async def ir_raw(self, frequency: int, timings: Sequence[int], port: int, repeats: int) -> None:
        """Send raw infrared timings on the raw IR topic."""
        await self._request(
            TOPIC_IR_RAW,
            "ir_raw",
            {"frequency": frequency, "timings": list(timings), "port": port, "repeats": repeats},
        )

    async def bt_key(self, key: str, action: KeyAction, target: str | None) -> None:
        """Send a Bluetooth HID key."""
        fields: dict[str, Any] = {"key": key, "keyAction": action.value}
        if target is not None:
            fields["target"] = target
        await self._command("bt_key", **fields)

    async def rf_wake(self, slot: int) -> None:
        """Wake the remote in a slot."""
        await self._command("rf_wake", slot=slot)

    async def rf_sleep(self, slot: int) -> None:
        """Put the remote in a slot to sleep."""
        await self._command("rf_sleep", slot=slot)

    async def push_config(self) -> None:
        """Push the configuration to the remotes."""
        await self._command("sync")

    async def activity_help(self) -> HelpResult:
        """Run Help on the current activity."""
        return HelpResult.from_json(await self._command("activity_help"))

    async def activity_help_answer(self, device_id: str, on: bool) -> None:
        """Answer the Help question for one device."""
        await self._command("activity_help_answer", device=device_id, on=on)

    async def update_check(self) -> UpdateStatus:
        """Ask the Hub for a release check; the reply carries the versions."""
        return UpdateStatus.from_json(
            await self._command("update_check", time_limit=UPDATE_CHECK_TIMEOUT)
        )

    async def update_apply(self) -> None:
        """Install the available release."""
        await self._command("update_apply")

    async def ir_capture(self, enabled: bool) -> None:
        """Start or stop infrared capture."""
        await self._command("ir_capture", enabled=enabled)

    # Internals

    async def _subscribe_all(self) -> None:
        subscriptions = {
            TOPIC_STATUS: self._handle_status,
            TOPIC_HUB: self._handle_state,
            TOPIC_ACTIVITY_STATE: self._handle_state,
            TOPIC_PROGRESS: self._handle_event,
            TOPIC_BT: self._handle_state,
            TOPIC_RF: self._handle_state,
            TOPIC_CONFIG: self._handle_config,
            TOPIC_INVENTORY_INDEX: self._handle_inventory,
            TOPIC_INVENTORY_DEVICE: self._handle_inventory,
            TOPIC_BUTTON: self._handle_event,
            TOPIC_IR_RECEIVED: self._handle_event,
            TOPIC_CMD_RESPONSE: self._handle_response,
        }
        for suffix, handler in subscriptions.items():
            self._unsubscribe.append(
                await mqtt.async_subscribe(self._hass, f"{self._base}/{suffix}", handler)
            )

    def _topic(self, full_topic: str) -> str:
        return full_topic.removeprefix(f"{self._base}/")

    @callback
    def _handle_status(self, message: mqtt.ReceiveMessage) -> None:
        online = str(message.payload).strip().casefold() == "online"
        was_online = self._hub_online
        self._hub_online = online
        if not self._ready or online == was_online:
            return
        if online:
            if self._on_snapshot is not None:
                self._on_snapshot(self._build_snapshot())
            if self._on_connection is not None:
                self._on_connection(True)
        elif self._on_connection is not None:
            self._on_connection(False)

    @callback
    def _handle_state(self, message: mqtt.ReceiveMessage) -> None:
        payload = _decode(message.payload)
        if payload is None:
            return
        topic = self._topic(message.topic)
        self._retained[topic] = payload
        if topic == TOPIC_HUB:
            if self._ready:
                try:
                    self._status = HubStatus.from_json(payload)
                except HarmonyNgUnsupportedError:
                    _LOGGER.debug("Ignoring a hub topic without identity")
                else:
                    # The Hub republishes it when its clock gets set (boot_time), on a
                    # configuration change and on Home Assistant's birth message
                    if self._hub_online and self._on_snapshot is not None:
                        self._on_snapshot(self._build_snapshot())
        elif self._ready:
            self._deliver(payload)
        self._retained_events[topic].set()

    @callback
    def _handle_event(self, message: mqtt.ReceiveMessage) -> None:
        payload = _decode(message.payload)
        if payload is not None and self._ready:
            self._deliver(payload)

    @callback
    def _handle_config(self, message: mqtt.ReceiveMessage) -> None:
        payload = _decode(message.payload)
        if payload is None:
            return
        version = payload.get("inventory_version")
        previous = self._retained.get(TOPIC_CONFIG)
        self._retained[TOPIC_CONFIG] = payload
        if previous is None or not self._ready or version == previous.get("inventory_version"):
            _LOGGER.debug(
                "Config topic: ready=%s version=%s previous=%s", self._ready, version, previous
            )
            return
        _LOGGER.debug("Inventory version changed to %s", version)
        if self._on_event is not None:
            seq = int(payload.get("seq") or 0)
            ts = int(payload.get("ts") or 0)
            self._on_event(
                ConfigChangedEvent("config_changed", seq, ts, files=("devices", "activities"))
            )

    @callback
    def _handle_inventory(self, message: mqtt.ReceiveMessage) -> None:
        topic = self._topic(message.topic)
        if not message.payload:
            if topic != TOPIC_INVENTORY_INDEX:
                self._chunks.pop(topic.removeprefix("inventory/"), None)
            self._inventory_changed.set()
            return
        payload = _decode(message.payload)
        if payload is None:
            return
        if topic == TOPIC_INVENTORY_INDEX:
            self._index = payload
        else:
            self._chunks[topic.removeprefix("inventory/")] = payload
        self._inventory_changed.set()

    @callback
    def _handle_response(self, message: mqtt.ReceiveMessage) -> None:
        payload = _decode(message.payload)
        if payload is None:
            return
        request_id = payload.get("id")
        future = self._pending.get(str(request_id)) if request_id is not None else None
        if future is not None and not future.done():
            future.set_result(payload)

    def _inventory_complete(self) -> bool:
        if self._index is None:
            return False
        wanted = [
            str(item.get("id"))
            for item in self._index.get("devices", [])
            if isinstance(item, Mapping)
        ]
        version = self._index.get("inventory_version")
        return all(
            device_id in self._chunks
            and self._chunks[device_id].get("inventory_version", version) == version
            for device_id in wanted
        )

    def _deliver(self, payload: Mapping[str, Any]) -> None:
        event = parse(payload)
        if event is None:
            _LOGGER.debug("Ignoring MQTT payload of type %r", payload.get("type"))
            return
        if self._on_event is not None:
            self._on_event(event)

    def _build_snapshot(self) -> Snapshot:
        config = self._retained.get(TOPIC_CONFIG, {})
        raw_files = config.get("files")
        files: Mapping[str, Any] = raw_files if isinstance(raw_files, Mapping) else {}
        payloads = [self._retained.get(t, {}) for t in STATE_TOPICS]
        seq = max((int(p.get("seq") or 0) for p in payloads), default=0)
        return Snapshot(
            hub=HubStatus.from_json(self._retained[TOPIC_HUB]),
            activity_state=ActivityState.from_json(self._retained.get(TOPIC_ACTIVITY_STATE, {})),
            bt_status=BtStatus.from_json(self._retained.get(TOPIC_BT, {})),
            rf_status=RfStatus.from_json(self._retained.get(TOPIC_RF, {})),
            config_files={str(k): int(v) for k, v in files.items() if isinstance(v, int)},
            seq=seq,
        )

    async def _command(
        self, action: str, *, time_limit: float | None = None, **fields: Any
    ) -> Mapping[str, Any]:
        return await self._request(TOPIC_CMD, action, {"action": action, **fields}, time_limit)

    async def _request(
        self,
        topic: str,
        action: str,
        fields: Mapping[str, Any],
        time_limit: float | None = None,
    ) -> Mapping[str, Any]:
        """Publish a request and wait for its acknowledgement on the response topic."""
        if not self.connected:
            raise HarmonyNgConnectionError("the Hub is not reachable through the broker")
        request_id = uuid4().hex[:12]
        future: asyncio.Future[Mapping[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await mqtt.async_publish(
                self._hass, f"{self._base}/{topic}", json.dumps({"id": request_id, **fields}), 1
            )
            async with asyncio.timeout(COMMAND_TIMEOUT if time_limit is None else time_limit):
                reply = await future
        except TimeoutError as err:
            raise HarmonyNgConnectionError(f"{action}: no reply from the Hub") from err
        finally:
            self._pending.pop(request_id, None)
        if reply.get("ok") is False:
            code = int(reply.get("code") or 0)
            error = str(reply.get("error") or f"{action} refused")
            if code == 409:
                raise HarmonyNgBusyError(error)
            if code in (401, 403):
                raise HarmonyNgAuthError(error)
            raise HarmonyNgApiError(error, code=code or None)
        return reply


def _decode(payload: Any) -> Mapping[str, Any] | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except TypeError, ValueError:
        return None
    return data if isinstance(data, Mapping) else None
