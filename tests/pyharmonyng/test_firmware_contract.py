"""The client library against payloads recorded from the firmware.

The files under fixtures/firmware are copied unchanged from the harmony-ng
firmware's tests/fixtures/ha, which the firmware builds with its real writers
(the RF status builder, hub_btstack's status file, a real infrared capture), at
branch hub/published-ir (b60f477), whose fixtures equal the prepared upstream chain.
The other fixtures are shaped for the integration tests; these keep the parsing
honest about the key names the firmware really uses.
"""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.harmony_ng.pyharmonyng import (
    CAP_IR_CAPTURE,
    Activity,
    BtStatus,
    Device,
    HarmonyNgClient,
    HubStatus,
    Inventory,
    IrSignal,
    RfStatus,
    Snapshot,
)

from .conftest import FakeHub, load_frames, load_json

FIRMWARE = "firmware/"
HOSTS = [
    ("AA:BB:CC:DD:EE:01", "Television", False),
    ("AA:BB:CC:DD:EE:FF", "Media Player", True),
]


def _hosts(status: BtStatus) -> list[tuple[str, str, bool]]:
    return [(h.bdaddr, h.name, h.connected) for h in status.hosts]


def test_status() -> None:
    status = HubStatus.from_json(load_json(FIRMWARE + "status"))
    assert status.hub_id == "20140101120000-000001"
    assert status.api_version >= 2
    assert status.boot_time == datetime.fromtimestamp(1794026082, tz=UTC)
    assert status.has(CAP_IR_CAPTURE)
    # Off after every Hub start: the receiver entity turns it on again
    assert status.ir_capture is False


def test_bt_status() -> None:
    """hub_btstack's file plus the fields hub_daemon adds; target is the physical remote."""
    status = BtStatus.from_json(load_json(FIRMWARE + "bt_status"))
    assert status.running and status.connected
    assert status.target == "AA:BB:CC:DD:EE:FF"
    assert _hosts(status) == HOSTS


def test_rf_slots() -> None:
    status = RfStatus.from_json(load_json(FIRMWARE + "rf_status"))
    paired = status.slot(1)
    assert paired is not None
    assert paired.active
    assert paired.model == "ultimate"
    assert paired.product_name == "Harmony Ultimate"
    assert (paired.skin, paired.equad_id) == (100, 16417)
    assert paired.battery_percent == 87
    assert paired.battery_reported_at == datetime.fromtimestamp(1794000000, tz=UTC)
    assert not paired.battery_restored
    empty = status.slot(2)
    assert empty is not None
    assert not empty.active
    assert empty.product_name is None
    # 0 % at 0 mV with a null reported_at: no report yet, not a reading
    assert empty.battery_percent is None
    assert empty.voltage_mv is None
    assert empty.charging is None
    assert empty.battery_reported_at is None


def test_inventory_and_activities() -> None:
    inventory = Inventory.from_json(load_json(FIRMWARE + "inventory"))
    assert inventory.devices
    assert all(device.type and device.commands for device in inventory.devices)
    activities = [Activity.from_json(a) for a in load_json(FIRMWARE + "activities")["activities"]]
    assert activities
    assert all(activity.type for activity in activities)


def test_snapshot() -> None:
    snapshot = Snapshot.from_json(load_json(FIRMWARE + "snapshot"))
    assert snapshot.hub.hub_id == "20140101120000-000001"
    assert _hosts(snapshot.bt_status) == HOSTS
    assert snapshot.rf_status.slot(1) is not None
    assert snapshot.hub.has(CAP_IR_CAPTURE)
    # Only GET /api/status says whether capture is on; the snapshot does not
    assert snapshot.hub.ir_capture is None


def test_mqtt_retained() -> None:
    retained = load_json(FIRMWARE + "mqtt_retained")
    index = retained["harmony/hub/inventory/index"]
    activities = [Activity.from_json(a) for a in index["activities"]]
    assert [a.type for a in activities] == ["WatchTV", "Custom"]
    chunks = [
        v for k, v in retained.items() if k.startswith("harmony/hub/inventory/") and k[-1].isdigit()
    ]
    devices = [Device.from_json(chunk) for chunk in chunks]
    assert sorted(d.type for d in devices) == ["MediaPlayer", "Television"]
    assert all(d.commands for d in devices)
    assert _hosts(BtStatus.from_json(retained["harmony/hub/bt"])) == HOSTS
    rf = RfStatus.from_json(retained["harmony/hub/rf"])
    assert rf.slot(1) is not None
    # ir/received is QoS 0 and never retained
    assert not any(topic.endswith("/ir/received") for topic in retained)


def test_ir_received() -> None:
    """A real capture: a soundbar's Volume Up."""
    (frame,) = load_frames(FIRMWARE + "ws_ir_received")
    assert frame["type"] == "ir_received"
    signal = IrSignal.from_json(frame)
    assert signal.modulation == 37700
    assert len(signal.timings) == len(frame["timings"]) > 2
    assert signal.timings[0] > 0 > signal.timings[1]
    # Too few carrier pulses to measure it: no modulation, the timings still count
    assert IrSignal.from_json({**frame, "modulation": None}).modulation is None


async def test_ir_capture_and_raw(client: HarmonyNgClient, hub: FakeHub) -> None:
    """The capture toggle's reply, and the request that sends timings back."""
    hub.responses["/api/ir-capture"] = (200, load_json(FIRMWARE + "ir_capture_response"))
    await client.ir_capture(True)
    request = load_json(FIRMWARE + "ir_raw_request")
    await client.ir_raw(
        request["frequency"], request["timings"], port=request["port"], repeats=request["repeats"]
    )
    assert hub.requests[-2:] == [
        ("POST", "/api/ir-capture", {"enabled": True}),
        ("POST", "/api/ir-raw", request),
    ]
