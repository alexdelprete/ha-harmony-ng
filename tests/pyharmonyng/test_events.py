"""Tests of the event parser."""

from __future__ import annotations

from custom_components.harmony_ng.pyharmonyng import (
    EVENT_TYPES,
    ActivityProgressEvent,
    ActivityStateEvent,
    ActivityStatus,
    BtStatusEvent,
    ButtonEvent,
    ConfigChangedEvent,
    IrReceivedEvent,
    MqttStatusEvent,
    RfStatusEvent,
    parse,
)

from .conftest import load_frames


def test_activity_switch_sequence() -> None:
    events = [parse(frame) for frame in load_frames("ws_activity_switch")]
    assert all(event is not None for event in events)
    kinds = [type(event).__name__ for event in events]
    assert kinds == [
        "ActivityStateEvent",
        "ActivityProgressEvent",
        "ActivityProgressEvent",
        "ActivityProgressEvent",
        "ActivityStateEvent",
        "ActivityStateEvent",
        "ActivityProgressEvent",
        "ActivityProgressEvent",
        "ActivityStateEvent",
    ]
    first = events[0]
    assert isinstance(first, ActivityStateEvent)
    assert first.type == "activity_state"
    assert first.seq == 43
    assert first.ts == 1762387243
    assert first.state.state is ActivityStatus.STARTING
    progress = events[1]
    assert isinstance(progress, ActivityProgressEvent)
    assert progress.progress.step == 1
    assert progress.progress.total == 3
    last = events[-1]
    assert isinstance(last, ActivityStateEvent)
    assert last.state.is_on is False
    assert [event.seq for event in events if event] == list(range(43, 52))


def test_button_events() -> None:
    press, release = (parse(frame) for frame in load_frames("ws_button"))
    assert isinstance(press, ButtonEvent)
    assert isinstance(release, ButtonEvent)
    assert press.button.action == "press"
    assert release.button.action == "release"
    assert press.button.button == "VolumeUp"
    assert press.button.slot == 1


def test_config_changed_event() -> None:
    (event,) = (parse(frame) for frame in load_frames("ws_config_changed"))
    assert isinstance(event, ConfigChangedEvent)
    assert event.files == ("devices",)
    assert event.inventory_changed
    settings_only = parse({"type": "config_changed", "files": ["settings"], "seq": 1, "ts": 1})
    assert isinstance(settings_only, ConfigChangedEvent)
    assert not settings_only.inventory_changed


def test_status_events() -> None:
    (rf,) = (parse(frame) for frame in load_frames("ws_rf_status"))
    assert isinstance(rf, RfStatusEvent)
    assert rf.status.active_slots[0].battery_percent == 87
    (bt,) = (parse(frame) for frame in load_frames("ws_bt_status"))
    assert isinstance(bt, BtStatusEvent)
    assert bt.status.hosts[0].connected


def test_non_events_are_ignored() -> None:
    assert parse({"type": "pong", "msgId": 1}) is None
    assert parse({"type": "ack", "ok": True}) is None
    assert parse({"type": "snapshot"}) is None
    assert parse({"type": "something_new", "seq": 1}) is None
    assert parse({"type": 5}) is None
    assert parse({}) is None


def test_event_types_listed() -> None:
    assert {
        "activity_state",
        "activity_progress",
        "config_changed",
        "bt_status",
        "rf_status",
        "button",
        "ir_received",
        "ir_capture",
        "mqtt_status",
    } == EVENT_TYPES


def test_mqtt_status_event() -> None:
    """Sent at start, on connect, on loss and after an MQTT settings save."""
    frame = {
        "type": "mqtt_status",
        "seq": 9,
        "ts": 0,
        "enabled": True,
        "connected": True,
        "broker": "broker.example",
        "port": 1883,
        "baseTopic": "harmony/hub",
        "haDiscovery": False,
    }
    event = parse(frame)
    assert isinstance(event, MqttStatusEvent)
    assert (event.seq, event.ha_discovery) == (9, False)
    del frame["haDiscovery"]
    event = parse(frame)
    assert isinstance(event, MqttStatusEvent)
    assert event.ha_discovery is None


def test_ir_received_event() -> None:
    (event,) = (parse(frame) for frame in load_frames("ws_ir_received"))
    assert isinstance(event, IrReceivedEvent)
    assert event.signal.modulation == 38000
    assert len(event.signal.timings) == 8
    assert "ir_received" in EVENT_TYPES
