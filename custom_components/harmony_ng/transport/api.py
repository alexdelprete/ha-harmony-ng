"""The API transport: REST plus one WebSocket, through pyharmonyng."""

from __future__ import annotations

from collections.abc import Sequence

import aiohttp

from custom_components.harmony_ng.pyharmonyng import (
    Activity,
    CommandAction,
    HarmonyNgClient,
    HarmonyNgConnectionError,
    HarmonyNgListener,
    HelpResult,
    HubStatus,
    Inventory,
    KeyAction,
    Snapshot,
)

from . import ConnectionCallback, EventCallback, SnapshotCallback

TRANSPORT_NAME = "api"


class ApiTransport:
    """REST for fetches and commands, the WebSocket for push and acknowledged commands."""

    name = TRANSPORT_NAME

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        port: int,
        token: str | None,
    ) -> None:
        """Build the client and the listener on the injected session."""
        self._client = HarmonyNgClient(host, session, port=port, token=token)
        self._listener: HarmonyNgListener | None = None
        self._host = host
        self._port = port
        self._session = session
        self._token = token
        self._status: HubStatus | None = None
        self._on_event: EventCallback | None = None
        self._on_connection: ConnectionCallback | None = None
        self._on_snapshot: SnapshotCallback | None = None

    @property
    def hub_id(self) -> str | None:
        """Return the Hub id read at connect."""
        return self._status.hub_id if self._status else None

    @property
    def status(self) -> HubStatus | None:
        """Return the status read at connect."""
        return self._status

    @property
    def capabilities(self) -> frozenset[str]:
        """Return the capability flags read at connect."""
        return self._status.capabilities if self._status else frozenset()

    @property
    def connected(self) -> bool:
        """Return whether the WebSocket is up."""
        return self._listener is not None and self._listener.connected

    @property
    def client(self) -> HarmonyNgClient:
        """Return the REST client, for the config flow's probes."""
        return self._client

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
        """Use another token for REST calls and the next WebSocket connection."""
        self._token = token
        self._client.set_token(token)
        if self._listener is not None:
            self._listener.set_token(token)

    async def connect(self) -> Snapshot:
        """Read the status, then open the WebSocket and return its snapshot."""
        self._status = await self._client.get_status()
        if self._on_event is None or self._on_connection is None or self._on_snapshot is None:
            raise RuntimeError("set_callbacks must be called before connect")
        listener = HarmonyNgListener(
            self._host,
            self._session,
            port=self._port,
            token=self._token,
            on_event=self._on_event,
            on_connection=self._on_connection,
            on_snapshot=self._on_snapshot,
        )
        snapshot = await listener.start()
        self._listener = listener
        self._status = snapshot.hub
        return snapshot

    async def disconnect(self) -> None:
        """Close the WebSocket."""
        listener, self._listener = self._listener, None
        if listener is not None:
            await listener.stop()

    async def fetch_inventory(self) -> Inventory:
        """Return the inventory over REST."""
        return await self._client.get_inventory()

    async def fetch_activities(self) -> tuple[Activity, ...]:
        """Return the activities over REST."""
        return await self._client.get_activities()

    async def start_activity(self, activity_id: str) -> None:
        """Start an activity, acknowledged over the socket when it is up."""
        if self._listener is not None and self._listener.connected:
            await self._listener.start_activity(activity_id)
            return
        await self._client.start_activity(activity_id)

    async def power_off(self) -> None:
        """Stop the running activity."""
        if self._listener is not None and self._listener.connected:
            await self._listener.power_off()
            return
        await self._client.power_off()

    async def cancel_activity(self) -> None:
        """Clear a stuck activity change."""
        if self._listener is not None and self._listener.connected:
            await self._listener.cancel_activity()
            return
        await self._client.cancel_activity()

    async def send_command(
        self, device_id: str, command: str, action: CommandAction, repeats: int
    ) -> None:
        """Send a device command.

        Press, hold and release exist only on the socket. A tap goes over REST when
        the socket is down, which also carries the repeat count.
        """
        if self._listener is not None and self._listener.connected:
            for _ in range(max(1, repeats) if action is CommandAction.TAP else 1):
                await self._listener.send_command(device_id, command, action=action)
            return
        if action is not CommandAction.TAP:
            raise HarmonyNgConnectionError("press, hold and release need the WebSocket")
        await self._client.send_command(device_id, command, repeats=repeats)

    async def ir_send(self, device_id: str, command: str, port: int, repeats: int) -> None:
        """Send a device command on given outputs, over REST."""
        await self._client.send_command(device_id, command, port=port, repeats=repeats)

    async def ir_raw(self, frequency: int, timings: Sequence[int], port: int, repeats: int) -> None:
        """Send raw infrared timings over REST."""
        await self._client.ir_raw(frequency, timings, port=port, repeats=repeats)

    async def bt_key(self, key: str, action: KeyAction, target: str | None) -> None:
        """Send a Bluetooth HID key."""
        if self._listener is not None and self._listener.connected:
            await self._listener.bt_key(key, action=action, target=target)
            return
        await self._client.bt_key(key, action=action, target=target)

    async def rf_wake(self, slot: int) -> None:
        """Wake the remote in a slot."""
        await self._client.rf_wake(slot)

    async def rf_sleep(self, slot: int) -> None:
        """Put the remote in a slot to sleep."""
        await self._client.rf_sleep(slot)

    async def push_config(self) -> None:
        """Push the configuration to the remotes."""
        await self._client.push_config()

    async def activity_help(self) -> HelpResult:
        """Run Help on the current activity."""
        return await self._client.activity_help()

    async def activity_help_answer(self, device_id: str, on: bool) -> None:
        """Answer the Help question for one device."""
        await self._client.activity_help_answer(device_id, on=on)
