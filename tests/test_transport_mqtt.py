"""Tests for the MQTT transport against the mocked MQTT integration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from datetime import timedelta
import json
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)
from pytest_homeassistant.typing import MqttMockHAClient

from custom_components.harmony_ng.const import (
    CONF_MQTT_BASE_TOPIC,
    CONF_TOKEN,
    CONF_TRANSPORT,
    DOMAIN,
    ISSUE_FIRMWARE_TOO_OLD,
    TRANSPORT_MQTT,
)
from custom_components.harmony_ng.pyharmonyng import (
    CommandAction,
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
    KeyAction,
)
from custom_components.harmony_ng.transport.mqtt import MqttTransport
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .conftest import HOST, HUB_ID
from .pyharmonyng.conftest import load_frames, load_json

BASE = "harmony/hub"
VERSION = "abc12345"


def retained_payloads(*, mqtt_v2: bool = True, online: bool = True) -> dict[str, str]:
    """Return topic to payload for a Hub running milestone 3 firmware."""
    snapshot = load_json("snapshot")
    hub = {**snapshot["hub"], "type": "hub", "seq": 42, "ts": 1}
    if mqtt_v2:
        hub["capabilities"] = [*hub["capabilities"], "mqtt_v2"]
    inventory = load_json("inventory")["devices"]
    index = {
        "type": "inventory_index",
        "inventory_version": VERSION,
        "devices": [
            {k: d[k] for k in ("id", "name", "type", "manufacturer", "model")} for d in inventory
        ],
        "activities": load_json("activities")["activities"],
    }
    payloads = {
        f"{BASE}/status": "online" if online else "offline",
        f"{BASE}/hub": json.dumps(hub),
        f"{BASE}/activity_state": json.dumps(
            {**snapshot["activity_state"], "type": "activity_state", "seq": 40}
        ),
        f"{BASE}/bt": json.dumps({**snapshot["bt_status"], "type": "bt_status", "seq": 41}),
        f"{BASE}/rf": json.dumps({**snapshot["rf_status"], "type": "rf_status", "seq": 42}),
        f"{BASE}/config": json.dumps(
            {"type": "config", "files": snapshot["config"]["files"], "inventory_version": VERSION}
        ),
        f"{BASE}/inventory/index": json.dumps(index),
    }
    for device in inventory:
        payloads[f"{BASE}/inventory/{device['id']}"] = json.dumps(
            {
                "type": "inventory_device",
                "inventory_version": VERSION,
                **{
                    k: device[k]
                    for k in ("id", "name", "type", "manufacturer", "model", "controlPort")
                },
                "commands": [c["name"] for c in device["commands"]],
            }
        )
    return payloads


def fire(hass: HomeAssistant, payloads: dict[str, str]) -> None:
    for topic, payload in payloads.items():
        async_fire_mqtt_message(hass, topic, payload, retain=True)


@pytest.fixture
def mqtt_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=HUB_ID,
        title="Living Room Hub",
        data={
            CONF_HOST: HOST,
            CONF_PORT: 8089,
            CONF_TOKEN: None,
            CONF_TRANSPORT: TRANSPORT_MQTT,
            CONF_MQTT_BASE_TOPIC: BASE,
        },
    )


async def setup_with_retained(
    hass: HomeAssistant, entry: MockConfigEntry, payloads: dict[str, str]
) -> None:
    """Set an entry up and deliver the retained topics once the transport subscribed.

    The mocked broker keeps nothing retained, so the messages must follow the
    subscriptions.
    """
    subscribed = asyncio.Event()
    original = MqttTransport._subscribe_all

    async def _subscribe_all(transport: MqttTransport) -> None:
        await original(transport)
        subscribed.set()

    with patch.object(MqttTransport, "_subscribe_all", _subscribe_all):
        task = hass.async_create_task(hass.config_entries.async_setup(entry.entry_id))
        await asyncio.wait_for(subscribed.wait(), 5)
        fire(hass, payloads)
        await task
    await hass.async_block_till_done()


async def flush_timers(hass: HomeAssistant) -> None:
    """Fire the MQTT client's subscribe and unsubscribe debouncers."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
async def no_lingering_timers(hass: HomeAssistant) -> AsyncGenerator[None]:
    """Flush the debouncers the MQTT client leaves behind after each test."""
    yield
    await flush_timers(hass)


async def setup_mqtt(
    hass: HomeAssistant, entry: MockConfigEntry, payloads: dict[str, str] | None = None
) -> None:
    """Set the entry up while the broker delivers the retained topics."""
    entry.add_to_hass(hass)
    await setup_with_retained(hass, entry, retained_payloads() if payloads is None else payloads)


def published(mqtt_mock: MqttMockHAClient) -> list[tuple[str, dict[str, Any]]]:
    return [
        (call.args[0], json.loads(call.args[1]))
        for call in mqtt_mock.async_publish.call_args_list
        if call.args[0].startswith(f"{BASE}/")
    ]


async def answer(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    action: Callable[[], Coroutine[Any, Any, Any]],
    reply: dict[str, Any],
) -> Any:
    """Run a command and answer its request on the response topic."""
    task = hass.async_create_task(action())
    await asyncio.sleep(0)
    topic, request = published(mqtt_mock)[-1]
    async_fire_mqtt_message(
        hass,
        f"{BASE}/cmd/response",
        json.dumps({"type": "cmd_response", "id": request["id"], **reply}),
    )
    return await task, topic, request


@pytest.mark.usefixtures("mqtt_mock")
async def test_setup_and_state(hass: HomeAssistant, mqtt_entry: MockConfigEntry) -> None:
    await setup_mqtt(hass, mqtt_entry)
    assert mqtt_entry.state is ConfigEntryState.LOADED
    coordinator = mqtt_entry.runtime_data.coordinator
    assert coordinator.transport_name == "mqtt"
    assert coordinator.transport.connected
    assert coordinator.configuration_url is None
    assert hass.states.get("remote.living_room_hub").state == "off"
    assert hass.states.get("remote.living_room_hub").attributes["activity_list"] == [
        "Watch TV",
        "Listen to Music",
    ]
    assert hass.states.get("sensor.harmony_ultimate_battery").state == "87"
    assert coordinator.data.inventory.version == VERSION
    assert [d.name for d in coordinator.data.inventory.devices] == [
        "LG OLED TV",
        "Soundbar",
        "Apple TV",
    ]
    assert coordinator.data.inventory.device("70321456").commands[0] == "PowerToggle"

    for frame in load_frames("ws_activity_switch")[:5]:
        async_fire_mqtt_message(
            hass,
            f"{BASE}/activity_state" if frame["type"] == "activity_state" else f"{BASE}/progress",
            json.dumps(frame),
        )
    await hass.async_block_till_done()
    assert hass.states.get("remote.living_room_hub").state == "on"
    assert hass.states.get("sensor.living_room_hub_activity_state").state == "running"

    async_fire_mqtt_message(
        hass, f"{BASE}/remote/1/button", json.dumps(load_frames("ws_button")[0])
    )
    await hass.async_block_till_done()
    assert hass.states.get("event.harmony_ultimate_button").attributes["button"] == "VolumeUp"

    async_fire_mqtt_message(hass, f"{BASE}/progress", "not json")
    async_fire_mqtt_message(hass, f"{BASE}/progress", json.dumps({"type": "unknown"}))
    await hass.async_block_till_done()


@pytest.mark.usefixtures("mqtt_mock")
async def test_offline_and_back(hass: HomeAssistant, mqtt_entry: MockConfigEntry) -> None:
    await setup_mqtt(hass, mqtt_entry)
    async_fire_mqtt_message(hass, f"{BASE}/status", "offline")
    await hass.async_block_till_done()
    assert hass.states.get("remote.living_room_hub").state == STATE_UNAVAILABLE
    transport = mqtt_entry.runtime_data.coordinator.transport
    assert not transport.connected
    with pytest.raises(HarmonyNgConnectionError, match="not reachable"):
        await transport.start_activity("123456")
    async_fire_mqtt_message(hass, f"{BASE}/status", "offline")
    async_fire_mqtt_message(hass, f"{BASE}/status", "online")
    await hass.async_block_till_done()
    assert hass.states.get("remote.living_room_hub").state == "off"


async def test_commands(
    hass: HomeAssistant, mqtt_entry: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    await setup_mqtt(hass, mqtt_entry)
    transport = mqtt_entry.runtime_data.coordinator.transport
    assert isinstance(transport, MqttTransport)

    _, topic, request = await answer(
        hass, mqtt_mock, lambda: transport.start_activity("123456"), {"ok": True}
    )
    assert topic == f"{BASE}/cmd"
    assert {k: v for k, v in request.items() if k != "id"} == {
        "action": "start_activity",
        "activity": "123456",
    }

    cases = [
        (transport.power_off, {"action": "stop_activity"}),
        (transport.cancel_activity, {"action": "cancel_activity"}),
        (
            lambda: transport.send_command("d", "c", CommandAction.TAP, 2),
            {"action": "send_command", "deviceId": "d", "command": "c", "repeats": 2},
        ),
        (
            lambda: transport.send_command("d", "c", CommandAction.HOLD, 1),
            {
                "action": "send_command",
                "deviceId": "d",
                "command": "c",
                "repeats": 1,
                "status": "hold",
            },
        ),
        (
            lambda: transport.ir_send("d", "c", 2, 3),
            {"action": "send_command", "deviceId": "d", "command": "c", "port": 2, "repeats": 3},
        ),
        (
            lambda: transport.bt_key("K", KeyAction.DOWN, "AA"),
            {"action": "bt_key", "key": "K", "keyAction": "down", "target": "AA"},
        ),
        (
            lambda: transport.bt_key("K", KeyAction.TAP, None),
            {"action": "bt_key", "key": "K", "keyAction": "tap"},
        ),
        (lambda: transport.rf_wake(1), {"action": "rf_wake", "slot": 1}),
        (lambda: transport.rf_sleep(0), {"action": "rf_sleep", "slot": 0}),
        (transport.push_config, {"action": "sync"}),
        (
            lambda: transport.activity_help_answer("d", False),
            {"action": "activity_help_answer", "device": "d", "on": False},
        ),
    ]
    for action, expected in cases:
        _, topic, request = await answer(hass, mqtt_mock, action, {"ok": True})
        assert topic == f"{BASE}/cmd"
        assert {k: v for k, v in request.items() if k != "id"} == expected

    result, topic, request = await answer(
        hass,
        mqtt_mock,
        transport.activity_help,
        {
            "ok": True,
            "activity": "123456",
            "toggleDevices": [{"id": "1", "name": "TV", "command": "PowerToggle"}],
        },
    )
    assert result.activity_id == "123456"
    assert result.toggle_devices[0].name == "TV"

    _, topic, request = await answer(
        hass, mqtt_mock, lambda: transport.ir_raw(38000, [1, -1], 1, 2), {"ok": True}
    )
    assert topic == f"{BASE}/ir/raw"
    assert {k: v for k, v in request.items() if k != "id"} == {
        "frequency": 38000,
        "timings": [1, -1],
        "port": 1,
        "repeats": 2,
    }

    transport.set_token("ignored")


async def test_command_errors(
    hass: HomeAssistant, mqtt_entry: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    await setup_mqtt(hass, mqtt_entry)
    transport = mqtt_entry.runtime_data.coordinator.transport
    with pytest.raises(HarmonyNgBusyError, match="busy"):
        await answer(
            hass,
            mqtt_mock,
            lambda: transport.start_activity("1"),
            {"ok": False, "code": 409, "error": "busy"},
        )
    with pytest.raises(HarmonyNgApiError, match="unknown activity") as info:
        await answer(
            hass,
            mqtt_mock,
            lambda: transport.start_activity("1"),
            {"ok": False, "code": 404, "error": "unknown activity"},
        )
    assert info.value.code == 404
    with pytest.raises(HarmonyNgApiError, match="refused"):
        await answer(hass, mqtt_mock, lambda: transport.start_activity("1"), {"ok": False})
    with pytest.raises(HarmonyNgAuthError):
        await answer(
            hass, mqtt_mock, lambda: transport.start_activity("1"), {"ok": False, "code": 401}
        )

    async_fire_mqtt_message(hass, f"{BASE}/cmd/response", json.dumps({"id": "nobody"}))
    async_fire_mqtt_message(hass, f"{BASE}/cmd/response", "junk")
    with (
        patch("custom_components.harmony_ng.transport.mqtt.COMMAND_TIMEOUT", 0.05),
        pytest.raises(HarmonyNgConnectionError, match="no reply"),
    ):
        await transport.start_activity("1")

    task = hass.async_create_task(transport.start_activity("1"))
    await asyncio.sleep(0)
    await transport.disconnect()
    with pytest.raises(HarmonyNgConnectionError, match="closed"):
        await task


@pytest.mark.usefixtures("mqtt_mock")
async def test_inventory_updates(hass: HomeAssistant, mqtt_entry: MockConfigEntry) -> None:
    await setup_mqtt(hass, mqtt_entry)
    coordinator = mqtt_entry.runtime_data.coordinator
    payloads = retained_payloads()
    new_version = "def67890"
    index = json.loads(payloads[f"{BASE}/inventory/index"])
    index["inventory_version"] = new_version
    index["devices"] = index["devices"][:2]
    index["activities"] = index["activities"][:1]
    async_fire_mqtt_message(hass, f"{BASE}/inventory/70321458", "")
    for device_id in ("70321456", "70321457"):
        chunk = json.loads(payloads[f"{BASE}/inventory/{device_id}"])
        chunk["inventory_version"] = new_version
        async_fire_mqtt_message(hass, f"{BASE}/inventory/{device_id}", json.dumps(chunk))
    async_fire_mqtt_message(hass, f"{BASE}/inventory/index", json.dumps(index))
    async_fire_mqtt_message(
        hass,
        f"{BASE}/config",
        json.dumps({"type": "config", "files": {}, "inventory_version": new_version, "seq": 50}),
    )
    await hass.async_block_till_done()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert coordinator.data.inventory.version == new_version
    assert [d.id for d in coordinator.data.inventory.devices] == ["70321456", "70321457"]
    assert [a.name for a in coordinator.data.activities] == ["Watch TV"]


@pytest.mark.usefixtures("mqtt_mock")
async def test_inventory_incomplete(hass: HomeAssistant, mqtt_entry: MockConfigEntry) -> None:
    payloads = retained_payloads()
    del payloads[f"{BASE}/inventory/70321458"]
    with patch("custom_components.harmony_ng.transport.mqtt.INVENTORY_TIMEOUT", 0.05):
        await setup_mqtt(hass, mqtt_entry, payloads)
    assert mqtt_entry.state is ConfigEntryState.SETUP_RETRY

    payloads = retained_payloads()
    del payloads[f"{BASE}/inventory/index"]
    entry = MockConfigEntry(domain=DOMAIN, unique_id=HUB_ID, title="Other", data=mqtt_entry.data)
    with patch("custom_components.harmony_ng.transport.mqtt.INVENTORY_TIMEOUT", 0.05):
        await setup_mqtt(hass, entry, payloads)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_without_mqtt(hass: HomeAssistant, mqtt_entry: MockConfigEntry) -> None:
    with patch(
        "custom_components.harmony_ng.transport.mqtt.mqtt.async_wait_for_mqtt_client",
        return_value=False,
    ):
        mqtt_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mqtt_entry.entry_id)
    assert mqtt_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mqtt_mock")
async def test_setup_failures(hass: HomeAssistant, mqtt_entry: MockConfigEntry) -> None:
    payloads = retained_payloads()
    del payloads[f"{BASE}/rf"]
    with patch("custom_components.harmony_ng.transport.mqtt.CONNECT_TIMEOUT", 0.05):
        await setup_mqtt(hass, mqtt_entry, payloads)
    assert mqtt_entry.state is ConfigEntryState.SETUP_RETRY

    old = MockConfigEntry(domain=DOMAIN, unique_id=HUB_ID, title="Old", data=mqtt_entry.data)
    await setup_mqtt(hass, old, retained_payloads(mqtt_v2=False))
    assert old.state is ConfigEntryState.SETUP_RETRY
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FIRMWARE_TOO_OLD) is not None

    offline = MockConfigEntry(
        domain=DOMAIN, unique_id=HUB_ID, title="Offline", data=mqtt_entry.data
    )
    await setup_mqtt(hass, offline, retained_payloads(online=False))
    assert offline.state is ConfigEntryState.SETUP_RETRY

    payloads = retained_payloads()
    payloads[f"{BASE}/hub"] = json.dumps({"type": "hub"})
    broken = MockConfigEntry(domain=DOMAIN, unique_id=HUB_ID, title="Broken", data=mqtt_entry.data)
    await setup_mqtt(hass, broken, payloads)
    assert broken.state is ConfigEntryState.SETUP_RETRY


async def test_connect_requires_callbacks(hass: HomeAssistant) -> None:
    transport = MqttTransport(hass, "harmony/hub/")
    assert transport.base_topic == "harmony/hub"
    assert transport.hub_id is None
    assert transport.capabilities == frozenset()
    with pytest.raises(RuntimeError, match="set_callbacks"):
        await transport.connect()


@pytest.mark.usefixtures("mqtt_mock")
async def test_odd_messages(hass: HomeAssistant, mqtt_entry: MockConfigEntry) -> None:
    await setup_mqtt(hass, mqtt_entry)
    transport = mqtt_entry.runtime_data.coordinator.transport
    assert isinstance(transport, MqttTransport)

    hub = json.loads(retained_payloads()[f"{BASE}/hub"])
    async_fire_mqtt_message(hass, f"{BASE}/hub", json.dumps({**hub, "version": "9.9.9"}))
    await hass.async_block_till_done()
    assert transport.status_version() == "9.9.9"
    async_fire_mqtt_message(hass, f"{BASE}/hub", json.dumps({"type": "hub"}))
    async_fire_mqtt_message(hass, f"{BASE}/hub", "junk")
    async_fire_mqtt_message(hass, f"{BASE}/rf", "[1, 2]")
    async_fire_mqtt_message(hass, f"{BASE}/inventory/index", "junk")
    async_fire_mqtt_message(hass, f"{BASE}/config", "junk")
    async_fire_mqtt_message(hass, f"{BASE}/status", "online")
    await hass.async_block_till_done()
    assert transport.status_version() == "9.9.9"
    assert transport.connected
    assert hass.states.get("remote.living_room_hub").state == "off"


async def test_status_before_ready(hass: HomeAssistant) -> None:
    transport = MqttTransport(hass, BASE)
    transport.set_callbacks(
        on_event=lambda _: None, on_connection=lambda _: None, on_snapshot=lambda _: None
    )
    message = type("Message", (), {"topic": f"{BASE}/status", "payload": "online"})()
    transport._handle_status(message)
    assert not transport.connected


async def test_update_and_capture(
    hass: HomeAssistant, mqtt_entry: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    await setup_mqtt(hass, mqtt_entry)
    transport = mqtt_entry.runtime_data.coordinator.transport
    assert isinstance(transport, MqttTransport)
    result, _, request = await answer(
        hass,
        mqtt_mock,
        transport.update_check,
        {
            "ok": True,
            "current_version": "2.2.0",
            "remote_version": "v2.3.0",
            "update_available": True,
        },
    )
    assert request["action"] == "update_check"
    assert result.latest_version == "2.3.0"
    for action, expected in (
        (transport.update_apply, {"action": "update_apply"}),
        (lambda: transport.ir_capture(True), {"action": "ir_capture", "enabled": True}),
    ):
        _, _, request = await answer(hass, mqtt_mock, action, {"ok": True})
        assert {k: v for k, v in request.items() if k != "id"} == expected

    received: list[Any] = []
    mqtt_entry.runtime_data.coordinator.async_add_ir_listener(received.append)
    async_fire_mqtt_message(
        hass, f"{BASE}/ir/received", json.dumps(load_frames("ws_ir_received")[0])
    )
    await hass.async_block_till_done()
    assert received[0].modulation == 38000
