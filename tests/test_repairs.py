"""Tests for the repair that removes the Hub's MQTT discovery device left behind."""

from __future__ import annotations

from dataclasses import replace

from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.repairs import process_repair_fix_flow, start_repair_fix_flow
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.harmony_ng.const import DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS
from custom_components.harmony_ng.repairs import async_find_discovery_orphans
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import HUB_ID, FakeTransport

OTHER_HUB_ID = "20140101120000-000099"


def add_discovery_device(
    hass: HomeAssistant, ident: str, hub_id: str | None, name: str = "Harmony Hub"
) -> dr.DeviceEntry:
    """Create the device and entities the Hub's MQTT discovery makes.

    Firmware before MQTT v2 put only the client id in the device's identifiers.
    """
    mqtt_entry = MockConfigEntry(domain="mqtt", title="MQTT")
    mqtt_entry.add_to_hass(hass)
    identifiers = {("mqtt", ident)}
    if hub_id is not None:
        identifiers.add(("mqtt", f"harmony-ng-{hub_id}"))
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt_entry.entry_id, identifiers=identifiers, name=name
    )
    entity_registry = er.async_get(hass)
    for suffix in ("activity", "ir_devices", "ir_commands", "power_off"):
        entity_registry.async_get_or_create(
            "sensor", "mqtt", f"{ident}_{suffix}", config_entry=mqtt_entry, device_id=device.id
        )
    return device


def discovery(fake_transport: FakeTransport, ha_discovery: bool | None) -> None:
    """Have the fake Hub report the discovery setting in its snapshot."""
    snapshot = fake_transport.snapshot
    fake_transport.snapshot = replace(
        snapshot, hub=replace(snapshot.hub, ha_discovery=ha_discovery)
    )


def mqtt_status(ha_discovery: bool) -> dict[str, object]:
    """Return the event the Hub sends after an MQTT settings save."""
    return {"type": "mqtt_status", "seq": 50, "ts": 0, "haDiscovery": ha_discovery}


def issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    """Return the discovery issue, if raised."""
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS)


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the integration up on the fake transport."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_orphans_detected_and_removed(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    fake_transport: FakeTransport,
) -> None:
    """Discovery off: only this Hub's device is offered, and the fix removes it."""
    assert await async_setup_component(hass, "repairs", {})
    orphan = add_discovery_device(hass, "harmony_hub", HUB_ID)
    other_hub = add_discovery_device(hass, "bedroom_hub", OTHER_HUB_ID, "Bedroom Hub")
    legacy = add_discovery_device(hass, "old_hub", None, "Old Hub")
    assert [d.id for d in async_find_discovery_orphans(hass, HUB_ID)] == [orphan.id]

    discovery(fake_transport, False)
    await setup(hass, mock_config_entry)
    raised = issue(hass)
    assert raised is not None
    assert raised.is_fixable
    assert raised.translation_placeholders == {"name": "Living Room Hub", "devices": "Harmony Hub"}

    client = await hass_client()
    flow = await start_repair_fix_flow(client, DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS)
    assert flow["step_id"] == "confirm"
    assert flow["description_placeholders"] == {"devices": "Harmony Hub"}
    result = await process_repair_fix_flow(client, flow["flow_id"], {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    devices = dr.async_get(hass)
    assert devices.async_get(orphan.id) is None
    assert devices.async_get(other_hub.id) is not None
    assert devices.async_get(legacy.id) is not None
    assert not [
        e
        for e in er.async_get(hass).entities.values()
        if e.platform == "mqtt" and e.device_id == orphan.id
    ]
    assert issue(hass) is None


async def test_no_issue_while_discovery_on(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The firmware default: the discovery device is the Hub's, live, and stays."""
    add_discovery_device(hass, "harmony_hub", HUB_ID)
    discovery(fake_transport, True)
    await setup(hass, mock_config_entry)
    assert issue(hass) is None


async def test_no_issue_while_setting_unknown(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """Firmware that does not report the setting: unknown is not off."""
    add_discovery_device(hass, "harmony_hub", HUB_ID)
    await setup(hass, mock_config_entry)
    assert issue(hass) is None


async def test_no_issue_without_orphans(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    discovery(fake_transport, False)
    await setup(hass, mock_config_entry)
    assert issue(hass) is None


async def test_issue_follows_the_setting(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """A settings save on WebSocket, a republished hub object on MQTT."""
    add_discovery_device(hass, "harmony_hub", HUB_ID)
    discovery(fake_transport, True)
    await setup(hass, mock_config_entry)
    assert issue(hass) is None

    fake_transport.push(mqtt_status(False))
    await hass.async_block_till_done()
    assert issue(hass) is not None

    # An mqtt_status without the setting keeps what the Hub reported before
    fake_transport.push({"type": "mqtt_status", "seq": 51, "ts": 0})
    await hass.async_block_till_done()
    assert issue(hass) is not None

    fake_transport.push(mqtt_status(True))
    await hass.async_block_till_done()
    assert issue(hass) is None

    discovery(fake_transport, False)
    fake_transport.restore()
    await hass.async_block_till_done()
    assert issue(hass) is not None
