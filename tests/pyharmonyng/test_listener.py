"""Tests of the WebSocket listener against the fake Hub."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp
import pytest

from custom_components.harmony_ng.pyharmonyng import (
    ActivityStateEvent,
    ButtonEvent,
    CommandAction,
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
    HarmonyNgError,
    HarmonyNgListener,
    HarmonyNgProtocolError,
    HubEvent,
    KeyAction,
    Snapshot,
)

from .conftest import FakeHub, load_frames

WAIT = 5.0
TOKEN = "pat_secret"  # noqa: S105


class Recorder:
    """Collects what the listener delivers, in queues the tests can await."""

    def __init__(self) -> None:
        self.events: asyncio.Queue[HubEvent] = asyncio.Queue()
        self.connections: asyncio.Queue[bool] = asyncio.Queue()
        self.snapshots: asyncio.Queue[Snapshot] = asyncio.Queue()

    async def event(self) -> HubEvent:
        return await asyncio.wait_for(self.events.get(), WAIT)

    async def connection(self) -> bool:
        return await asyncio.wait_for(self.connections.get(), WAIT)

    async def snapshot(self) -> Snapshot:
        return await asyncio.wait_for(self.snapshots.get(), WAIT)


def make_listener(
    hub: FakeHub, session: aiohttp.ClientSession, **kwargs: Any
) -> tuple[HarmonyNgListener, Recorder]:
    recorder = Recorder()
    listener = HarmonyNgListener(
        hub.host,
        session,
        port=hub.port,
        on_event=recorder.events.put_nowait,
        on_connection=recorder.connections.put_nowait,
        on_snapshot=recorder.snapshots.put_nowait,
        backoff=(0.01,),
        **kwargs,
    )
    return listener, recorder


@pytest.fixture
async def started(
    hub: FakeHub, session: aiohttp.ClientSession
) -> AsyncGenerator[tuple[HarmonyNgListener, Recorder, Snapshot]]:
    listener, recorder = make_listener(hub, session)
    snapshot = await listener.start()
    try:
        yield listener, recorder, snapshot
    finally:
        await listener.stop()


async def wait_for_clients(hub: FakeHub, count: int) -> None:
    async with asyncio.timeout(WAIT):
        while len(hub.clients) != count:  # noqa: ASYNC110
            await asyncio.sleep(0.01)


async def test_start_returns_snapshot(
    started: tuple[HarmonyNgListener, Recorder, Snapshot],
) -> None:
    listener, _, snapshot = started
    assert snapshot.seq == 42
    assert snapshot.gap is False
    assert snapshot.hub.hub_id == "20140101120000-000001"
    assert listener.connected
    assert listener.last_seq == 42
    assert listener.url.startswith("ws://127.0.0.1:")


async def test_events_are_delivered(
    started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub
) -> None:
    listener, recorder, _ = started
    for frame in load_frames("ws_activity_switch"):
        await hub.push(frame)
    received = [await recorder.event() for _ in range(9)]
    assert isinstance(received[0], ActivityStateEvent)
    assert [event.seq for event in received] == list(range(43, 52))
    assert listener.last_seq == 51
    await hub.push(load_frames("ws_button")[0])
    event = await recorder.event()
    assert isinstance(event, ButtonEvent)
    assert event.button.button == "VolumeUp"


async def test_unknown_and_broken_frames_are_ignored(
    started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub
) -> None:
    _, recorder, _ = started
    await hub.push({"type": "something_new", "seq": 99})
    for client in hub.clients:
        await client.send_str("not json")
        await client.send_str("[1, 2]")
    await hub.push(load_frames("ws_config_changed")[0])
    event = await recorder.event()
    assert event.type == "config_changed"
    assert recorder.events.empty()


async def test_reconnect_and_gap(
    started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub
) -> None:
    listener, recorder, _ = started
    await hub.push(load_frames("ws_activity_switch")[0])
    await recorder.event()
    hub.snapshot = {**hub.snapshot, "seq": 60}
    await hub.drop_clients()
    assert await recorder.connection() is False
    assert listener.connected is False
    snapshot = await recorder.snapshot()
    assert snapshot.seq == 60
    assert snapshot.gap is True
    assert await recorder.connection() is True
    assert listener.connected
    assert listener.last_seq == 60
    assert hub.connections == 2

    hub.snapshot = {**hub.snapshot, "seq": 60}
    await hub.drop_clients()
    assert await recorder.connection() is False
    snapshot = await recorder.snapshot()
    assert snapshot.gap is False
    assert await recorder.connection() is True


async def test_reconnect_retries_until_the_hub_answers(
    hub: FakeHub, session: aiohttp.ClientSession
) -> None:
    listener, recorder = make_listener(hub, session)
    await listener.start()
    hub.first_frame = {"type": "pong"}
    await hub.drop_clients()
    assert await recorder.connection() is False
    await wait_for_clients(hub, 0)
    await asyncio.sleep(0.05)
    assert hub.connections >= 2
    assert listener.connected is False
    hub.first_frame = None
    assert await recorder.connection() is True
    await listener.stop()
    assert listener.connected is False


async def test_silence_drops_the_socket(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    listener, recorder = make_listener(hub, session, silence_timeout=0.1)
    await listener.start()
    assert await recorder.connection() is False
    assert await recorder.connection() is True
    assert hub.connections >= 2
    await listener.stop()


async def test_stop_while_reconnecting(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    listener, recorder = make_listener(hub, session)
    await listener.start()
    hub.first_frame = {"type": "pong"}
    await hub.drop_clients()
    assert await recorder.connection() is False
    await listener.stop()
    assert listener.connected is False
    with pytest.raises(HarmonyNgConnectionError):
        await listener.send_action("ping")


async def test_actions(started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub) -> None:
    listener, _, _ = started
    await listener.start_activity("123456")
    await listener.power_off()
    await listener.cancel_activity()
    await listener.send_command("70321456", "VolumeUp")
    await listener.send_command("70321456", "VolumeUp", action=CommandAction.PRESS)
    await listener.bt_key("KEY_ENTER")
    await listener.bt_key("KEY_UP", action=KeyAction.DOWN, target="AA:BB:CC:DD:EE:FF")
    await listener.ir_capture(True)
    reply = await listener.send_action("ping")
    assert reply["type"] == "pong"
    assert [{k: v for k, v in action.items() if k != "msgId"} for action in hub.actions] == [
        {"action": "start_activity", "id": "123456"},
        {"action": "stop_activity"},
        {"action": "cancel_activity"},
        {"action": "send_command", "deviceId": "70321456", "command": "VolumeUp"},
        {
            "action": "send_command",
            "deviceId": "70321456",
            "command": "VolumeUp",
            "cmdAction": "press",
        },
        {"action": "bt_key", "key": "KEY_ENTER", "keyAction": "tap"},
        {"action": "bt_key", "key": "KEY_UP", "keyAction": "down", "target": "AA:BB:CC:DD:EE:FF"},
        {"action": "ir_capture", "enabled": True},
        {"action": "ping"},
    ]
    assert [action["msgId"] for action in hub.actions] == list(range(1, 10))


async def test_request_snapshot(
    started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub
) -> None:
    listener, recorder, _ = started
    hub.snapshot = {**hub.snapshot, "seq": 70}
    snapshot = await listener.request_snapshot()
    assert snapshot.seq == 70
    assert listener.last_seq == 70
    assert recorder.snapshots.empty()


async def test_unsolicited_snapshot(
    started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub
) -> None:
    listener, recorder, _ = started
    await hub.push({**hub.snapshot, "seq": 80})
    snapshot = await recorder.snapshot()
    assert snapshot.seq == 80
    assert listener.last_seq == 80


async def test_ack_errors(
    started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub
) -> None:
    listener, _, _ = started
    hub.ack_error = "Interlock busy"
    with pytest.raises(HarmonyNgBusyError, match="Interlock busy"):
        await listener.start_activity("123456")
    hub.ack_error = "unknown device"
    with pytest.raises(HarmonyNgApiError, match="unknown device"):
        await listener.send_command("x", "y")
    hub.ack_error = ""
    with pytest.raises(HarmonyNgApiError, match="refused"):
        await listener.send_command("x", "y")


async def test_missing_ack(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    listener, _ = make_listener(hub, session, ack_timeout=0.05)
    await listener.start()
    hub.silent_acks = True
    with pytest.raises(HarmonyNgConnectionError, match="no reply"):
        await listener.start_activity("123456")
    await listener.stop()


async def test_pending_requests_fail_on_drop(
    started: tuple[HarmonyNgListener, Recorder, Snapshot], hub: FakeHub
) -> None:
    listener, recorder, _ = started
    hub.silent_acks = True
    task = asyncio.create_task(listener.start_activity("123456"))
    await asyncio.sleep(0.05)
    await hub.drop_clients()
    with pytest.raises(HarmonyNgConnectionError, match="dropped"):
        await task
    assert await recorder.connection() is False
    assert await recorder.connection() is True


async def test_start_errors(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    hub.first_frame = {"type": "pong"}
    listener, _ = make_listener(hub, session)
    with pytest.raises(HarmonyNgProtocolError, match="expected a snapshot"):
        await listener.start()
    assert not hub.clients

    hub.first_frame = None
    hub.required_token = TOKEN
    with pytest.raises(HarmonyNgAuthError):
        await listener.start()
    listener.set_token(TOKEN)
    snapshot = await listener.start()
    assert snapshot.seq == 42
    with pytest.raises(HarmonyNgError, match="already running"):
        await listener.start()
    await listener.stop()

    refused = HarmonyNgListener(
        "127.0.0.1",
        session,
        port=1,
        on_event=lambda _: None,
        on_connection=lambda _: None,
    )
    with pytest.raises(HarmonyNgConnectionError):
        await refused.start()


async def test_closed_before_snapshot(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    hub.close_before_snapshot = True
    listener, _ = make_listener(hub, session)
    with pytest.raises(HarmonyNgConnectionError, match="before the snapshot"):
        await listener.start()


async def test_upgrade_refused(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    hub.ws_status = 500
    listener, _ = make_listener(hub, session)
    with pytest.raises(HarmonyNgConnectionError, match="upgrade refused: 500"):
        await listener.start()


async def test_no_snapshot_after_upgrade(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    hub.silent_connect = True
    listener, _ = make_listener(hub, session, handshake_timeout=0.1)
    with pytest.raises(HarmonyNgConnectionError, match="no snapshot"):
        await listener.start()
    await wait_for_clients(hub, 0)


async def test_reconnect_survives_refused_upgrades(
    hub: FakeHub, session: aiohttp.ClientSession
) -> None:
    listener, recorder = make_listener(hub, session)
    await listener.start()
    hub.ws_status = 503
    await hub.drop_clients()
    assert await recorder.connection() is False
    await asyncio.sleep(0.05)
    assert listener.connected is False
    hub.ws_status = None
    assert await recorder.connection() is True
    await listener.stop()


async def test_stop_without_start(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    listener, _ = make_listener(hub, session)
    await listener.stop()
    assert listener.connected is False
