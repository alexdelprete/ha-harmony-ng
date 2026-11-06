"""Tests of the models, parsing the recorded fixtures."""

from __future__ import annotations

import pytest

from custom_components.harmony_ng.pyharmonyng import (
    POWER_OFF_ACTIVITY_ID,
    Activity,
    ActivityProgress,
    ActivityState,
    ActivityStatus,
    BtStatus,
    Device,
    HarmonyNgUnsupportedError,
    HelpResult,
    HubStatus,
    Inventory,
    MqttInfo,
    RemoteButton,
    RfSlot,
    RfStatus,
    Snapshot,
)
from custom_components.harmony_ng.pyharmonyng.models import _bool, _int, _opt_int, _opt_str, _str

from .conftest import load_frames, load_json


def test_hub_status_from_fixture() -> None:
    status = HubStatus.from_json(load_json("status"))
    assert status.hub_id == "20140101120000-000001"
    assert status.hub_name == "Living Room Hub"
    assert status.version == "2.2.0"
    assert status.commit == "abc1234"
    assert status.api_version == 2
    assert status.has("events")
    assert not status.has("mqtt_v2")
    assert status.auth_enabled is False
    assert status.uptime_sec == 34821
    assert status.firmware == "4.15.600"
    assert status.mqtt == MqttInfo(connected=False, broker="", port=1883, base_topic="harmony/hub")


def test_hub_status_accepts_documented_mqtt_keys() -> None:
    data = {
        **load_json("status"),
        "mqtt": {"host": "broker", "base_topic": "x/y", "connected": True},
    }
    status = HubStatus.from_json(data)
    assert status.mqtt == MqttInfo(connected=True, broker="broker", port=1883, base_topic="x/y")


def test_hub_status_without_mqtt_and_uptime() -> None:
    data = {k: v for k, v in load_json("status").items() if k not in ("mqtt", "uptime_sec")}
    status = HubStatus.from_json(data)
    assert status.mqtt is None
    assert status.uptime_sec is None


def test_hub_status_rejects_old_firmware() -> None:
    data = load_json("status")
    with pytest.raises(HarmonyNgUnsupportedError, match="hub_id"):
        HubStatus.from_json({k: v for k, v in data.items() if k != "hub_id"})
    with pytest.raises(HarmonyNgUnsupportedError, match="API version 1"):
        HubStatus.from_json({**data, "api_version": 1})


def test_activity_status_codes() -> None:
    assert ActivityStatus.from_code(0) is ActivityStatus.IDLE
    assert ActivityStatus.from_code(1) is ActivityStatus.STARTING
    assert ActivityStatus.from_code(2) is ActivityStatus.RUNNING
    assert ActivityStatus.from_code(3) is ActivityStatus.STOPPING
    assert ActivityStatus.from_code(9) is ActivityStatus.IDLE


def test_activity_state_from_rest_and_event() -> None:
    rest = ActivityState.from_json(load_json("activity"))
    assert rest == ActivityState(POWER_OFF_ACTIVITY_ID, ActivityStatus.IDLE, False, False)
    assert rest.is_on is False
    event = ActivityState.from_json(load_frames("ws_activity_switch")[0])
    assert event == ActivityState("123456", ActivityStatus.STARTING, True, True)
    assert event.is_on is True
    assert ActivityState.from_json({}).activity_id == POWER_OFF_ACTIVITY_ID


def test_activity_progress() -> None:
    progress = ActivityProgress.from_json(load_frames("ws_activity_switch")[1])
    assert progress == ActivityProgress(
        "123456", ActivityStatus.STARTING, 1, 3, "LG OLED TV PowerToggle"
    )


def test_activities_and_inventory() -> None:
    activities = [Activity.from_json(item) for item in load_json("activities")["activities"]]
    assert [a.name for a in activities] == ["Watch TV", "Listen to Music"]
    assert activities[0] == Activity("123456", "Watch TV", "Custom", 1)

    inventory = Inventory.from_json(load_json("inventory"))
    assert inventory.version is None
    assert [d.id for d in inventory.devices] == ["70321456", "70321457", "70321458"]
    tv = inventory.device("70321456")
    assert tv is not None
    assert tv.commands == ("PowerToggle", "VolumeUp", "VolumeDown", "Mute", "InputHdmi2")
    assert tv.has_command("volumeup")
    assert not tv.has_command("Play")
    assert inventory.device_by_name("soundbar") == inventory.device("70321457")
    assert inventory.device("nope") is None
    assert inventory.device_by_name("nope") is None


def test_device_from_mqtt_chunk() -> None:
    device = Device.from_json(
        {
            "id": "1",
            "name": "X",
            "commands": ["A", {"name": "B"}, {"raw": "no name"}, 7],
            "control_port": 2,
            "inventory_version": "abc",
        }
    )
    assert device.commands == ("A", "B")
    assert device.control_port == 2
    assert (
        Inventory.from_json({"devices": [{"id": "1"}, "junk"], "inventory_version": "abc"}).version
        == "abc"
    )


def test_rf_status() -> None:
    status = RfStatus.from_json(load_json("rf_status"))
    assert status.running and status.connected and status.paired
    assert status.pairing_active is False
    assert len(status.slots) == 2
    assert len(status.active_slots) == 1
    slot = status.slot(1)
    assert slot == RfSlot(
        slot=1,
        active=True,
        remote_id="20141001120000-000002",
        model="Harmony Ultimate",
        has_screen=True,
        battery_percent=87,
        charging=False,
        voltage_mv=3980,
        config_version=12,
        hub_config_version=12,
        in_sync=True,
        sw_version="2.2.0",
        last_seen_s=2,
    )
    empty = status.slot(2)
    assert empty is not None
    assert empty.active is False
    assert empty.remote_id is None
    assert empty.battery_percent is None
    assert empty.charging is None
    assert empty.in_sync is None
    assert status.slot(3) is None


def test_bt_status() -> None:
    status = BtStatus.from_json(load_json("bt_status"))
    assert status.running and status.connected
    assert status.target == "AA:BB:CC:DD:EE:FF"
    assert [(h.name, h.connected) for h in status.hosts] == [("Apple TV", True), ("Shield", False)]
    offline = BtStatus.from_json({**load_json("bt_status"), "connected": False, "target": ""})
    assert offline.target is None
    assert all(not h.connected for h in offline.hosts)


def test_remote_button() -> None:
    press = RemoteButton.from_json(load_frames("ws_button")[0])
    assert press == RemoteButton(1, "VolumeUp", "press", "70321456", "VolumeUp", "elite_rf")
    minimal = RemoteButton.from_json({"command": "Menu"})
    assert minimal == RemoteButton(1, "Menu", "press", None, "Menu", "")


def test_snapshot() -> None:
    snapshot = Snapshot.from_json(load_json("snapshot"))
    assert snapshot.hub.hub_id == "20140101120000-000001"
    assert snapshot.activity_state.state is ActivityStatus.IDLE
    assert snapshot.rf_status.active_slots[0].remote_id == "20141001120000-000002"
    assert snapshot.bt_status.hosts[0].connected
    assert snapshot.config_files == {
        "devices": 1762387000,
        "activities": 1762387000,
        "settings": 1762380000,
        "remote_map": 1762387000,
    }
    assert snapshot.seq == 42
    assert snapshot.gap is False
    assert snapshot.with_gap(True).gap is True


def test_help_result() -> None:
    result = HelpResult.from_json(load_json("help"))
    assert result.activity_id == "123456"
    assert [(d.id, d.command) for d in result.toggle_devices] == [("70321456", "PowerToggle")]
    assert HelpResult.from_json({}).activity_id == POWER_OFF_ACTIVITY_ID


def test_helpers_tolerate_odd_values() -> None:
    assert _int({"a": "12"}, "a") == 12
    assert _int({"a": "-1"}, "a") == -1
    assert _int({"a": "x"}, "a", default=5) == 5
    assert _int({"a": True}, "a") == 1
    assert _int({"a": 2.7}, "a") == 2
    assert _opt_int({"a": None}, "a") is None
    assert _str({"a": None, "b": 3}, "a", "b") == "3"
    assert _opt_str({"a": ""}, "a") is None
    assert _bool({"a": 0}, "a", default=True) is False
