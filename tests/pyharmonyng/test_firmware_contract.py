"""The client library against payloads recorded from the firmware.

The files under fixtures/firmware are copied unchanged from the harmony-ng
firmware's tests/fixtures/ha (commit f2f5290), which records what its daemons
send. The other fixtures are shaped for the integration tests; these keep the
parsing honest about key names the firmware really uses.
"""

from __future__ import annotations

from custom_components.harmony_ng.pyharmonyng import (
    Activity,
    BtStatus,
    Device,
    HubStatus,
    Inventory,
    RfStatus,
    Snapshot,
)

from .conftest import load_json

FIRMWARE = "firmware/"


def test_status() -> None:
    status = HubStatus.from_json(load_json(FIRMWARE + "status"))
    assert status.hub_id == "20140101120000-000001"
    assert status.api_version >= 2


def test_bt_hosts_use_addr() -> None:
    status = BtStatus.from_json(load_json(FIRMWARE + "bt_status"))
    assert [(h.bdaddr, h.name, h.connected) for h in status.hosts] == [
        ("AA:BB:CC:DD:EE:FF", "Media Player", True)
    ]


def test_rf_slots() -> None:
    status = RfStatus.from_json(load_json(FIRMWARE + "rf_status"))
    paired = status.slot(1)
    assert paired is not None
    assert paired.active
    assert paired.model == "elite"
    # This firmware does not report the product yet, so the model is not shown
    assert paired.product_name is None
    assert paired.battery_percent is not None
    empty = status.slot(2)
    assert empty is not None
    assert not empty.active
    # 0 % at 0 mV is the Hub's placeholder before a report, not a reading
    assert empty.battery_percent is None
    assert empty.voltage_mv is None
    assert empty.charging is None


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
    assert [h.bdaddr for h in snapshot.bt_status.hosts] == ["AA:BB:CC:DD:EE:FF"]
    assert snapshot.rf_status.slot(1) is not None


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
    bt = BtStatus.from_json(retained["harmony/hub/bt"])
    assert [h.bdaddr for h in bt.hosts] == ["AA:BB:CC:DD:EE:FF"]
    rf = RfStatus.from_json(retained["harmony/hub/rf"])
    assert rf.slot(1) is not None
