"""Tests for the API transport's routing between REST and the WebSocket."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.harmony_ng.pyharmonyng import (
    CommandAction,
    HarmonyNgConnectionError,
    HubStatus,
    KeyAction,
    Snapshot,
    UpdateStatus,
)
from custom_components.harmony_ng.transport.api import ApiTransport

from .pyharmonyng.conftest import load_json


@pytest.fixture
def client() -> Generator[MagicMock]:
    with patch("custom_components.harmony_ng.transport.api.HarmonyNgClient") as cls:
        instance = MagicMock()
        for name in (
            "get_status",
            "get_inventory",
            "get_activities",
            "start_activity",
            "power_off",
            "cancel_activity",
            "send_command",
            "ir_raw",
            "bt_key",
            "rf_wake",
            "rf_sleep",
            "push_config",
            "activity_help",
            "activity_help_answer",
        ):
            setattr(instance, name, AsyncMock())
        instance.get_status.return_value = HubStatus.from_json(load_json("status"))
        cls.return_value = instance
        yield instance


@pytest.fixture
def listener() -> Generator[MagicMock]:
    with patch("custom_components.harmony_ng.transport.api.HarmonyNgListener") as cls:
        instance = MagicMock()
        instance.connected = True
        instance.start = AsyncMock(return_value=Snapshot.from_json(load_json("snapshot")))
        instance.stop = AsyncMock()
        for name in ("start_activity", "power_off", "cancel_activity", "send_command", "bt_key"):
            setattr(instance, name, AsyncMock())
        cls.return_value = instance
        yield instance


def make_transport() -> ApiTransport:
    return ApiTransport("hub", MagicMock(spec=aiohttp.ClientSession), port=8089, token=None)


async def test_connect_requires_callbacks(client: MagicMock, listener: MagicMock) -> None:
    transport = make_transport()
    assert transport.hub_id is None
    assert transport.capabilities == frozenset()
    assert transport.connected is False
    with pytest.raises(RuntimeError, match="set_callbacks"):
        await transport.connect()


async def test_connect_and_route(client: MagicMock, listener: MagicMock) -> None:
    transport = make_transport()
    transport.set_callbacks(
        on_event=lambda _: None, on_connection=lambda _: None, on_snapshot=lambda _: None
    )
    snapshot = await transport.connect()
    assert snapshot.seq == 42
    assert transport.hub_id == "20140101120000-000001"
    assert "events" in transport.capabilities
    assert transport.connected

    await transport.start_activity("1")
    await transport.power_off()
    await transport.cancel_activity()
    await transport.send_command("d", "c", CommandAction.TAP, 2)
    await transport.send_command("d", "c", CommandAction.PRESS, 5)
    await transport.bt_key("K", KeyAction.TAP, None)
    listener.start_activity.assert_awaited_once_with("1")
    listener.power_off.assert_awaited_once()
    listener.cancel_activity.assert_awaited_once()
    assert listener.send_command.await_count == 3
    listener.bt_key.assert_awaited_once_with("K", action=KeyAction.TAP, target=None)
    client.start_activity.assert_not_awaited()

    await transport.ir_send("d", "c", 2, 3)
    await transport.ir_raw(38000, [1, -1], 1, 1)
    await transport.rf_wake(1)
    await transport.rf_sleep(0)
    await transport.push_config()
    await transport.activity_help()
    await transport.activity_help_answer("d", False)
    await transport.fetch_inventory()
    await transport.fetch_activities()
    client.send_command.assert_awaited_once_with("d", "c", port=2, repeats=3)
    client.ir_raw.assert_awaited_once_with(38000, [1, -1], port=1, repeats=1)
    client.rf_wake.assert_awaited_once_with(1)
    client.rf_sleep.assert_awaited_once_with(0)
    client.push_config.assert_awaited_once()
    client.activity_help.assert_awaited_once()
    client.activity_help_answer.assert_awaited_once_with("d", on=False)
    client.get_inventory.assert_awaited_once()
    client.get_activities.assert_awaited_once()

    transport.set_token("pat_new")
    client.set_token.assert_called_once_with("pat_new")
    listener.set_token.assert_called_once_with("pat_new")

    await transport.disconnect()
    listener.stop.assert_awaited_once()
    assert transport.connected is False


async def test_rest_fallback_when_socket_is_down(client: MagicMock, listener: MagicMock) -> None:
    transport = make_transport()
    transport.set_callbacks(
        on_event=lambda _: None, on_connection=lambda _: None, on_snapshot=lambda _: None
    )
    await transport.connect()
    listener.connected = False

    await transport.start_activity("1")
    await transport.power_off()
    await transport.cancel_activity()
    await transport.send_command("d", "c", CommandAction.TAP, 2)
    await transport.bt_key("K", KeyAction.DOWN, "AA")
    client.start_activity.assert_awaited_once_with("1")
    client.power_off.assert_awaited_once()
    client.cancel_activity.assert_awaited_once()
    client.send_command.assert_awaited_once_with("d", "c", repeats=2)
    client.bt_key.assert_awaited_once_with("K", action=KeyAction.DOWN, target="AA")
    with pytest.raises(HarmonyNgConnectionError):
        await transport.send_command("d", "c", CommandAction.PRESS, 1)
    transport.set_token(None)
    client.set_token.assert_called_once_with(None)


async def test_update_and_capture(client: MagicMock, listener: MagicMock) -> None:
    client.get_update_status = AsyncMock(return_value=UpdateStatus("2.2.0", "2.3.0", True, ""))
    client.update_check = AsyncMock(return_value=UpdateStatus("2.2.0", None, True, "newer"))
    client.update_apply = AsyncMock()
    client.ir_capture = AsyncMock()
    listener.ir_capture = AsyncMock()
    transport = make_transport()
    transport.set_callbacks(
        on_event=lambda _: None, on_connection=lambda _: None, on_snapshot=lambda _: None
    )
    await transport.connect()
    status = await transport.update_check()
    assert status == UpdateStatus("2.2.0", "2.3.0", True, "newer")
    await transport.update_apply()
    client.update_apply.assert_awaited_once()
    await transport.ir_capture(True)
    listener.ir_capture.assert_awaited_once_with(True)
    listener.connected = False
    await transport.ir_capture(False)
    client.ir_capture.assert_awaited_once_with(False)
