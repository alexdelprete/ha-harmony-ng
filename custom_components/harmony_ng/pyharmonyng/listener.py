"""WebSocket listener for the Harmony NG Hub.

The listener owns the socket, the snapshot handshake, the reconnect policy and the
request and acknowledgement matching. Whoever uses it only reacts to callbacks.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
import contextlib
import json
import logging
from typing import Any, Final

import aiohttp

from .client import DEFAULT_PORT
from .events import HubEvent, parse
from .exceptions import (
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
    HarmonyNgError,
    HarmonyNgProtocolError,
)
from .models import CommandAction, KeyAction, Snapshot

_LOGGER = logging.getLogger(__name__)

DEFAULT_BACKOFF: Final[tuple[float, ...]] = (1, 2, 4, 8, 16, 30)
DEFAULT_SILENCE_TIMEOUT: Final = 45.0
"""Seconds without any frame before the socket counts as dead; the Hub pings every 30 s."""
DEFAULT_ACK_TIMEOUT: Final = 10.0
HANDSHAKE_TIMEOUT: Final = 10.0

FRAME_SNAPSHOT: Final = "snapshot"
FRAME_ACK: Final = "ack"
FRAME_PONG: Final = "pong"

type EventCallback = Callable[[HubEvent], None]
type ConnectionCallback = Callable[[bool], None]
type SnapshotCallback = Callable[[Snapshot], None]


class HarmonyNgListener:
    """Keeps one WebSocket to the Hub open and delivers what it pushes."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        on_event: EventCallback,
        on_connection: ConnectionCallback,
        on_snapshot: SnapshotCallback | None = None,
        port: int = DEFAULT_PORT,
        token: str | None = None,
        backoff: Sequence[float] = DEFAULT_BACKOFF,
        silence_timeout: float = DEFAULT_SILENCE_TIMEOUT,
        ack_timeout: float = DEFAULT_ACK_TIMEOUT,
        handshake_timeout: float = HANDSHAKE_TIMEOUT,
    ) -> None:
        """Keep the parameters; `start` opens the socket.

        Args:
            host: the Hub's host.
            session: the aiohttp session, never closed by the listener.
            on_event: called for every event the Hub pushes.
            on_connection: called with False when the socket drops and with True
                after the snapshot of a reconnect.
            on_snapshot: called with the snapshot of every reconnect; the first
                snapshot is returned by `start` instead.
            port: the Hub's HTTP port.
            token: a Personal Access Token or session token when auth is enabled.
            backoff: delays between reconnect attempts; the last one repeats.
            silence_timeout: seconds without a frame before the socket is dropped.
            ack_timeout: seconds to wait for the acknowledgement of a request.
            handshake_timeout: seconds allowed for the upgrade and the first snapshot.
        """
        self._host = host
        self._port = port
        self._session = session
        self._token = token
        self._on_event = on_event
        self._on_connection = on_connection
        self._on_snapshot = on_snapshot
        self._backoff = tuple(backoff) or DEFAULT_BACKOFF
        self._silence_timeout = silence_timeout
        self._ack_timeout = ack_timeout
        self._handshake_timeout = handshake_timeout
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._connected = False
        self._last_seq: int | None = None
        self._next_msg_id = 1
        self._pending: dict[int, asyncio.Future[Mapping[str, Any]]] = {}

    @property
    def connected(self) -> bool:
        """Return whether the socket is open and the snapshot was received."""
        return self._connected

    @property
    def last_seq(self) -> int | None:
        """Return the bus sequence of the last event or snapshot processed."""
        return self._last_seq

    @property
    def url(self) -> str:
        """Return the WebSocket URL."""
        return f"ws://{self._host}:{self._port}/ws"

    def set_token(self, token: str | None) -> None:
        """Use another token for the next connection."""
        self._token = token

    async def start(self) -> Snapshot:
        """Connect, read the first snapshot and start listening in the background.

        Raises:
            HarmonyNgConnectionError: the Hub cannot be reached.
            HarmonyNgAuthError: the Hub refused the token on the upgrade.
            HarmonyNgProtocolError: the first frame was not a snapshot.
        """
        if self._task is not None:
            raise HarmonyNgError("the listener is already running")
        self._stopping = False
        ws = await self._connect()
        try:
            snapshot = await self._read_snapshot(ws)
        except BaseException:
            await ws.close()
            raise
        self._ws = ws
        self._connected = True
        self._last_seq = snapshot.seq
        self._task = asyncio.create_task(self._run(), name="pyharmonyng.listener")
        return snapshot

    async def stop(self) -> None:
        """Close the socket and stop reconnecting."""
        self._stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._close_socket()
        self._connected = False

    async def request_snapshot(self) -> Snapshot:
        """Ask the Hub for a fresh snapshot."""
        reply = await self.send_action("get_snapshot")
        snapshot = Snapshot.from_json(reply)
        self._last_seq = max(self._last_seq or 0, snapshot.seq)
        return snapshot

    async def send_action(self, action: str, **fields: Any) -> Mapping[str, Any]:
        """Send a request frame and return the Hub's reply to it.

        Raises:
            HarmonyNgConnectionError: the socket is down or the reply never came.
            HarmonyNgBusyError: the Hub refused because the orchestrator is busy.
            HarmonyNgApiError: the Hub refused for another reason.
        """
        ws = self._ws
        if not self._connected or ws is None:
            raise HarmonyNgConnectionError("the WebSocket is not connected")
        msg_id = self._next_msg_id
        self._next_msg_id += 1
        future: asyncio.Future[Mapping[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        try:
            await ws.send_json({"action": action, "msgId": msg_id, **fields})
            async with asyncio.timeout(self._ack_timeout):
                reply = await future
        except (aiohttp.ClientError, ConnectionError) as err:
            raise HarmonyNgConnectionError(f"{action}: {err}") from err
        except TimeoutError as err:
            raise HarmonyNgConnectionError(
                f"{action}: no reply within {self._ack_timeout} s"
            ) from err
        finally:
            self._pending.pop(msg_id, None)
        if reply.get("type") == FRAME_ACK and reply.get("ok") is False:
            error = str(reply.get("error") or f"{action} refused")
            if "busy" in error.casefold():
                raise HarmonyNgBusyError(error)
            raise HarmonyNgApiError(error)
        return reply

    async def start_activity(self, activity_id: str) -> None:
        """Start an activity through the socket."""
        await self.send_action("start_activity", id=activity_id)

    async def power_off(self) -> None:
        """Stop the running activity through the socket."""
        await self.send_action("stop_activity")

    async def cancel_activity(self) -> None:
        """Clear a stuck activity change through the socket."""
        await self.send_action("cancel_activity")

    async def send_command(
        self, device_id: str, command: str, *, action: CommandAction = CommandAction.TAP
    ) -> None:
        """Send a device command as a tap, or as one press, hold or release."""
        fields: dict[str, Any] = {"deviceId": device_id, "command": command}
        if action is not CommandAction.TAP:
            fields["cmdAction"] = action.value
        await self.send_action("send_command", **fields)

    async def bt_key(
        self, key: str, *, action: KeyAction = KeyAction.TAP, target: str | None = None
    ) -> None:
        """Send a Bluetooth HID key through the socket."""
        fields: dict[str, Any] = {"key": key, "keyAction": action.value}
        if target is not None:
            fields["target"] = target
        await self.send_action("bt_key", **fields)

    async def _connect(self) -> aiohttp.ClientWebSocketResponse:
        params = {"token": self._token} if self._token else None
        try:
            async with asyncio.timeout(self._handshake_timeout):
                return await self._session.ws_connect(self.url, params=params, heartbeat=None)
        except aiohttp.WSServerHandshakeError as err:
            if err.status in (401, 403):
                raise HarmonyNgAuthError("the Hub refused the token on the upgrade") from err
            raise HarmonyNgConnectionError(f"upgrade refused: {err.status}") from err
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            raise HarmonyNgConnectionError(f"cannot connect to {self.url}: {err}") from err

    async def _read_snapshot(self, ws: aiohttp.ClientWebSocketResponse) -> Snapshot:
        """Read the frame the Hub sends first after an upgrade."""
        try:
            message = await ws.receive(timeout=self._handshake_timeout)
        except TimeoutError as err:
            raise HarmonyNgConnectionError("no snapshot after the upgrade") from err
        if message.type is not aiohttp.WSMsgType.TEXT:
            raise HarmonyNgConnectionError(
                f"socket closed before the snapshot ({message.type.name})"
            )
        frame = _decode(message.data)
        if frame.get("type") != FRAME_SNAPSHOT:
            raise HarmonyNgProtocolError(f"expected a snapshot, got {frame.get('type')!r}")
        return Snapshot.from_json(frame)

    async def _run(self) -> None:
        """Pump frames and reconnect until stopped."""
        while not self._stopping:
            ws = self._ws
            if ws is not None:
                await self._pump(ws)
            self._mark_disconnected()
            if self._stopping:
                return
            await self._reconnect()

    async def _pump(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Deliver frames until the socket closes, errors or falls silent."""
        while True:
            try:
                message = await ws.receive(timeout=self._silence_timeout)
            except TimeoutError:
                _LOGGER.debug("No frame for %s s, dropping the socket", self._silence_timeout)
                return
            except aiohttp.ClientError as err:
                _LOGGER.debug("Socket error: %s", err)
                return
            if message.type is aiohttp.WSMsgType.TEXT:
                try:
                    self._handle_frame(_decode(message.data))
                except HarmonyNgError as err:
                    _LOGGER.debug("Ignoring a frame the Hub sent: %s", err)
            elif message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                _LOGGER.debug("Socket closed (%s)", message.type.name)
                return

    def _mark_disconnected(self) -> None:
        was_connected = self._connected
        self._connected = False
        for future in self._pending.values():
            if not future.done():
                future.set_exception(HarmonyNgConnectionError("the WebSocket dropped"))
        self._pending.clear()
        if was_connected:
            self._on_connection(False)

    async def _reconnect(self) -> None:
        """Reconnect with backoff until it works or `stop` is called."""
        await self._close_socket()
        attempt = 0
        while not self._stopping:
            delay = self._backoff[min(attempt, len(self._backoff) - 1)]
            attempt += 1
            await asyncio.sleep(delay)
            if self._stopping:
                return
            try:
                ws = await self._connect()
            except HarmonyNgError as err:
                _LOGGER.debug("Reconnect attempt %s failed: %s", attempt, err)
                continue
            try:
                snapshot = await self._read_snapshot(ws)
            except HarmonyNgError as err:
                _LOGGER.debug("Reconnect attempt %s failed: %s", attempt, err)
                await ws.close()
                continue
            gap = self._last_seq is not None and snapshot.seq > self._last_seq
            self._ws = ws
            self._connected = True
            self._last_seq = snapshot.seq
            if self._on_snapshot is not None:
                self._on_snapshot(snapshot.with_gap(gap))
            self._on_connection(True)
            return

    async def _close_socket(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None and not ws.closed:
            with contextlib.suppress(aiohttp.ClientError, OSError):
                await ws.close()

    def _handle_frame(self, frame: Mapping[str, Any]) -> None:
        frame_type = frame.get("type")
        msg_id = frame.get("msgId")
        if frame_type in (FRAME_SNAPSHOT, FRAME_ACK, FRAME_PONG):
            if isinstance(msg_id, int) and (future := self._pending.get(msg_id)) is not None:
                if not future.done():
                    future.set_result(frame)
            elif frame_type == FRAME_SNAPSHOT:
                self._deliver_snapshot(frame)
            return
        event = parse(frame)
        if event is None:
            _LOGGER.debug("Unknown frame type %r ignored", frame_type)
            return
        if event.seq:
            self._last_seq = max(self._last_seq or 0, event.seq)
        self._on_event(event)

    def _deliver_snapshot(self, frame: Mapping[str, Any]) -> None:
        """Pass an unsolicited snapshot on, since it carries the full state."""
        snapshot = Snapshot.from_json(frame)
        self._last_seq = max(self._last_seq or 0, snapshot.seq)
        if self._on_snapshot is not None:
            self._on_snapshot(snapshot)


def _decode(data: str) -> Mapping[str, Any]:
    try:
        frame = json.loads(data)
    except ValueError as err:
        raise HarmonyNgProtocolError(f"frame is not JSON: {err}") from err
    if not isinstance(frame, Mapping):
        raise HarmonyNgProtocolError("frame is not a JSON object")
    return frame
