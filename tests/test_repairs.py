"""Tests for the repair that removes the Hub's old MQTT discovery entities."""

from __future__ import annotations

from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.repairs import process_repair_fix_flow, start_repair_fix_flow
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.harmony_ng.const import DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS
from custom_components.harmony_ng.repairs import async_find_discovery_orphans
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import FakeTransport


def add_old_discovery(hass: HomeAssistant, ident: str, *, complete: bool = True) -> dr.DeviceEntry:
    """Create what the Hub's old firmware left in the mqtt registries."""
    mqtt_entry = MockConfigEntry(domain="mqtt", title="MQTT")
    mqtt_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt_entry.entry_id, identifiers={("mqtt", ident)}, name="Harmony Hub"
    )
    entity_registry = er.async_get(hass)
    suffixes = ["activity", "ir_devices"] + (["ir_commands", "power_off"] if complete else [])
    for suffix in suffixes:
        entity_registry.async_get_or_create(
            "sensor", "mqtt", f"{ident}_{suffix}", config_entry=mqtt_entry, device_id=device.id
        )
    return device


async def test_orphans_detected_and_removed(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    fake_transport: FakeTransport,
) -> None:
    assert await async_setup_component(hass, "repairs", {})
    orphan = add_old_discovery(hass, "harmony_hub")
    partial = add_old_discovery(hass, "other_hub", complete=False)
    assert [d.id for d in async_find_discovery_orphans(hass)] == [orphan.id]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS)
    assert issue is not None
    assert issue.translation_placeholders == {"name": "Living Room Hub", "devices": "Harmony Hub"}

    client = await hass_client()
    flow = await start_repair_fix_flow(client, DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS)
    assert flow["step_id"] == "confirm"
    assert flow["description_placeholders"] == {"devices": "Harmony Hub"}
    result = await process_repair_fix_flow(client, flow["flow_id"], {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert dr.async_get(hass).async_get(orphan.id) is None
    assert dr.async_get(hass).async_get(partial.id) is not None
    assert not [
        e
        for e in er.async_get(hass).entities.values()
        if e.platform == "mqtt" and e.device_id == orphan.id
    ]
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS) is None


async def test_no_issue_without_orphans(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MQTT_DISCOVERY_ORPHANS) is None
