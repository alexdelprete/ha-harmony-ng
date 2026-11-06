"""Tests for setup, unload and device removal."""

from __future__ import annotations

from pytest_homeassistant.common import MockConfigEntry

from custom_components.harmony_ng import async_remove_config_entry_device, build_transport
from custom_components.harmony_ng.const import (
    CONF_MQTT_BASE_TOPIC,
    CONF_TRANSPORT,
    DOMAIN,
    ISSUE_FIRMWARE_TOO_OLD,
    ISSUE_LEGACY_ENABLED,
    TRANSPORT_MQTT,
)
from custom_components.harmony_ng.pyharmonyng import (
    HarmonyNgAuthError,
    HarmonyNgConnectionError,
    HarmonyNgUnsupportedError,
    Snapshot,
)
from custom_components.harmony_ng.transport.api import ApiTransport
from custom_components.harmony_ng.transport.mqtt import MqttTransport
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .conftest import HUB_ID, REMOTE_ID, FakeTransport
from .pyharmonyng.conftest import load_json


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    assert [c[0] for c in fake_transport.calls if c[0] != "update_check"] == [
        "connect",
        "fetch_activities",
        "fetch_inventory",
    ]
    device_registry = dr.async_get(hass)
    hub = device_registry.async_get_device_by_identifier((DOMAIN, HUB_ID), entry.entry_id)
    assert hub is not None
    assert hub.serial_number == HUB_ID
    assert hub.sw_version == "2.2.0"
    assert hub.configuration_url == "http://192.0.2.10:8089"
    remote = device_registry.async_get_device_by_identifier((DOMAIN, REMOTE_ID), entry.entry_id)
    assert remote is not None
    assert remote.via_device_id == hub.id
    assert remote.model == "Harmony Ultimate"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert fake_transport.calls[-1] == ("disconnect", ())


async def test_setup_retries_when_unreachable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fake_transport.connect_error = HarmonyNgConnectionError("refused")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_starts_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fake_transport.connect_error = HarmonyNgAuthError("bad token")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_setup_old_firmware_raises_issue(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fake_transport.connect_error = HarmonyNgUnsupportedError("API version 1 is below 2")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FIRMWARE_TOO_OLD)
    assert issue is not None
    assert issue.translation_placeholders == {
        "name": "Living Room Hub",
        "error": "API version 1 is below 2",
    }


async def test_setup_hub_mismatch(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    other = load_json("snapshot")
    other["hub"]["hub_id"] = "20140101120000-000009"
    fake_transport.snapshot = Snapshot.from_json(other)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert fake_transport.calls[-1] == ("disconnect", ())


async def test_legacy_issue_follows_the_hub(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    legacy = load_json("snapshot")
    legacy["hub"]["legacy_enabled"] = True
    fake_transport.snapshot = Snapshot.from_json(legacy)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, ISSUE_LEGACY_ENABLED) is not None

    fake_transport.restore(Snapshot.from_json(load_json("snapshot")))
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE_LEGACY_ENABLED) is None


async def test_remove_device(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    device_registry = dr.async_get(hass)
    hub = device_registry.async_get_device_by_identifier((DOMAIN, HUB_ID), entry.entry_id)
    remote = device_registry.async_get_device_by_identifier((DOMAIN, REMOTE_ID), entry.entry_id)
    assert hub is not None and remote is not None
    assert await async_remove_config_entry_device(hass, entry, hub) is False
    assert await async_remove_config_entry_device(hass, entry, remote) is False
    stale = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{HUB_ID}:slot2")}
    )
    assert await async_remove_config_entry_device(hass, entry, stale) is True


async def test_build_transport(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    mock_config_entry.add_to_hass(hass)
    transport = build_transport(hass, mock_config_entry)
    assert isinstance(transport, ApiTransport)
    assert transport.client.base_url == "http://192.0.2.10:8089"

    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            CONF_TRANSPORT: TRANSPORT_MQTT,
            CONF_MQTT_BASE_TOPIC: "harmony/hub",
        },
    )
    transport = build_transport(hass, mock_config_entry)
    assert isinstance(transport, MqttTransport)
    assert transport.base_topic == "harmony/hub"
