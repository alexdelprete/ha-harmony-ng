"""Tests of the REST client against the fake Hub."""

from __future__ import annotations

import aiohttp
import pytest

from custom_components.harmony_ng.pyharmonyng import (
    DEFAULT_PORT,
    ActivityStatus,
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgBusyError,
    HarmonyNgClient,
    HarmonyNgConnectionError,
    HarmonyNgUnsupportedError,
    KeyAction,
)

from .conftest import FakeHub, load_json

TOKEN = "pat_secret"  # noqa: S105


def test_properties(session: aiohttp.ClientSession) -> None:
    client = HarmonyNgClient("hub.local", session)
    assert client.host == "hub.local"
    assert client.port == DEFAULT_PORT
    assert client.base_url == "http://hub.local:8089"
    assert client.token is None
    client.set_token(TOKEN)
    assert client.token == TOKEN


async def test_reads(client: HarmonyNgClient, hub: FakeHub) -> None:
    status = await client.get_status()
    assert status.hub_id == "20140101120000-000001"
    inventory = await client.get_inventory()
    assert len(inventory.devices) == 3
    activities = await client.get_activities()
    assert [a.id for a in activities] == ["123456", "234567"]
    state = await client.get_activity_state()
    assert state.state is ActivityStatus.IDLE
    rf = await client.get_rf_status()
    assert rf.active_slots[0].slot == 1
    bt = await client.get_bt_status()
    assert bt.target == "AA:BB:CC:DD:EE:FF"
    assert [path for _, path, _ in hub.requests] == [
        "/api/status",
        "/api/inventory",
        "/api/activities",
        "/api/activity",
        "/api/rf/status",
        "/api/bt-status",
    ]
    assert all(body is None for _, _, body in hub.requests)


async def test_activities_malformed(client: HarmonyNgClient, hub: FakeHub) -> None:
    hub.responses["/api/activities"] = (200, {"activities": "nope"})
    assert await client.get_activities() == ()
    hub.responses["/api/activities"] = (200, {"activities": [{"id": "1", "name": "A"}, "junk"]})
    assert [a.id for a in await client.get_activities()] == ["1"]


async def test_old_firmware(client: HarmonyNgClient, hub: FakeHub) -> None:
    hub.responses["/api/status"] = (200, {"ok": True, "hub_name": "old"})
    with pytest.raises(HarmonyNgUnsupportedError):
        await client.get_status()


async def test_token_header(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    hub.required_token = TOKEN
    client = HarmonyNgClient(hub.host, session, port=hub.port)
    with pytest.raises(HarmonyNgAuthError, match="unauthorized"):
        await client.get_status()
    client.set_token(TOKEN)
    assert (await client.get_status()).hub_id


async def test_error_mapping(client: HarmonyNgClient, hub: FakeHub) -> None:
    hub.responses["/api/activity"] = (409, {"ok": False, "error": "Interlock busy"})
    with pytest.raises(HarmonyNgBusyError, match="Interlock busy"):
        await client.start_activity("123456")

    hub.responses["/api/activity"] = (403, {"message": "forbidden"})
    with pytest.raises(HarmonyNgAuthError, match="forbidden"):
        await client.start_activity("123456")

    hub.responses["/api/activity"] = (500, "not json")
    with pytest.raises(HarmonyNgApiError, match="HTTP 500") as info:
        await client.start_activity("123456")
    assert info.value.code == 500

    hub.responses["/api/activity"] = (200, {"success": False, "error": "unknown activity"})
    with pytest.raises(HarmonyNgApiError, match="unknown activity") as info:
        await client.start_activity("123456")
    assert info.value.code == 200
    assert info.value.message == "unknown activity"

    hub.responses["/api/activity"] = (200, {"ok": False})
    with pytest.raises(HarmonyNgApiError, match="refused"):
        await client.start_activity("123456")

    hub.responses["/api/activity"] = (200, "plain text")
    await client.start_activity("123456")


async def test_connection_errors(hub: FakeHub, session: aiohttp.ClientSession) -> None:
    refused = HarmonyNgClient("127.0.0.1", session, port=1)
    with pytest.raises(HarmonyNgConnectionError):
        await refused.get_status()

    hub.delay = 0.5
    slow = HarmonyNgClient(hub.host, session, port=hub.port, request_timeout=0.05)
    with pytest.raises(HarmonyNgConnectionError):
        await slow.get_status()


async def test_commands(client: HarmonyNgClient, hub: FakeHub) -> None:
    await client.start_activity("123456")
    await client.power_off()
    await client.cancel_activity()
    await client.send_command("70321456", "VolumeUp")
    await client.send_command("70321456", "VolumeUp", port=2, repeats=3)
    await client.bt_key("KEY_ENTER")
    await client.bt_key("KEY_UP", action=KeyAction.DOWN, target="AA:BB:CC:DD:EE:FF")
    await client.rf_wake(1)
    await client.rf_sleep(0)
    await client.push_config()
    await client.activity_help_answer("70321456", on=False)
    assert hub.requests == [
        ("POST", "/api/activity", {"activity": "123456"}),
        ("POST", "/api/poweroff", {}),
        ("POST", "/api/activity-cancel", {}),
        ("POST", "/api/ir-send", {"deviceId": "70321456", "command": "VolumeUp", "repeats": 1}),
        (
            "POST",
            "/api/ir-send",
            {"deviceId": "70321456", "command": "VolumeUp", "repeats": 3, "port": 2},
        ),
        ("POST", "/api/bt-key", {"key": "KEY_ENTER", "keyAction": "tap"}),
        (
            "POST",
            "/api/bt-key",
            {"key": "KEY_UP", "keyAction": "down", "target": "AA:BB:CC:DD:EE:FF"},
        ),
        ("POST", "/api/rf/wake?slot=1", {}),
        ("POST", "/api/rf/sleep?slot=0", {}),
        ("POST", "/api/rf/push-config", {}),
        ("POST", "/api/activity/help/answer", {"device": "70321456", "on": False}),
    ]


async def test_help(client: HarmonyNgClient) -> None:
    result = await client.activity_help()
    assert result.activity_id == "123456"
    assert result.toggle_devices[0].name == "LG OLED TV"


async def test_ir_raw(client: HarmonyNgClient, hub: FakeHub) -> None:
    request = load_json("ir_raw_request")
    await client.ir_raw(request["frequency"], request["timings"], port=request["port"])
    assert hub.requests == [("POST", "/api/ir-raw", request)]
    await client.ir_raw(0, (100, 100), port=7, repeats=10)
    assert hub.requests[-1][2] == {"frequency": 0, "timings": [100, 100], "port": 7, "repeats": 10}


@pytest.mark.parametrize(
    ("frequency", "timings", "port", "repeats", "match"),
    [
        (10000, [100, -100], 1, 1, "frequency"),
        (70000, [100, -100], 1, 1, "frequency"),
        (38000, [100], 1, 1, "timings"),
        (38000, [100] * 2049, 1, 1, "timings"),
        (38000, [100, 0], 1, 1, "microseconds"),
        (38000, [100, -70000], 1, 1, "microseconds"),
        (38000, [100, -100], 0, 1, "port"),
        (38000, [100, -100], 8, 1, "port"),
        (38000, [100, -100], 1, 0, "repeats"),
        (38000, [100, -100], 1, 11, "repeats"),
    ],
)
async def test_ir_raw_validation(
    client: HarmonyNgClient,
    hub: FakeHub,
    frequency: int,
    timings: list[int],
    port: int,
    repeats: int,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        await client.ir_raw(frequency, timings, port=port, repeats=repeats)
    assert hub.requests == []


async def test_update_and_capture(client: HarmonyNgClient, hub: FakeHub) -> None:
    hub.responses["/api/update-status"] = (200, load_json("update_status"))
    hub.responses["/api/update-check"] = (200, load_json("update_check"))
    status = await client.get_update_status()
    assert status.latest_version == "2.3.0"
    check = await client.update_check()
    assert check.update_available
    await client.update_apply()
    await client.ir_capture(True)
    assert hub.requests[-3:] == [
        ("POST", "/api/update-check", {}),
        ("POST", "/api/update-apply", {}),
        ("POST", "/api/ir-capture", {"enabled": True}),
    ]


async def test_update_check_outlives_the_request_timeout(
    hub: FakeHub, session: aiohttp.ClientSession
) -> None:
    """The Hub's release check retries downloads; only the check may take that long."""
    client = HarmonyNgClient(hub.host, session, port=hub.port, request_timeout=0.05)
    hub.responses["/api/update-check"] = (200, load_json("update_check"))
    hub.delay = 0.2
    assert (await client.update_check()).update_available
    with pytest.raises(HarmonyNgConnectionError):
        await client.update_apply()
