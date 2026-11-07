"""Tests for the firmware update entity."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.harmony_ng.pyharmonyng import (
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
    Snapshot,
    UpdateStatus,
)
from homeassistant.components.update import DOMAIN as UPDATE_DOMAIN, SERVICE_INSTALL
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_json

ENTITY = "update.living_room_hub_firmware"


@pytest.fixture(autouse=True)
def only_update() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.UPDATE]):
        yield


async def test_entity(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_versions_and_install(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(ENTITY)
    assert state.state == "on"
    assert state.attributes["installed_version"] == "2.2.0"
    assert state.attributes["latest_version"] == "2.3.0"
    assert state.attributes["title"] == "harmony-ng"
    assert state.attributes["message"] == "A newer release is available (v2.3.0)."
    assert [c for c in fake_transport.calls if c[0] == "update_check"] == [("update_check", ())]

    fake_transport.errors["update_apply"] = HarmonyNgBusyError("busy")
    with pytest.raises(HomeAssistantError, match="busy"):
        await hass.services.async_call(
            UPDATE_DOMAIN, SERVICE_INSTALL, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )
    assert hass.states.get(ENTITY).attributes["in_progress"] is False
    del fake_transport.errors["update_apply"]

    await hass.services.async_call(
        UPDATE_DOMAIN, SERVICE_INSTALL, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert fake_transport.commands()[-1] == ("update_apply", ())
    assert hass.states.get(ENTITY).attributes["in_progress"] is False

    updated = load_json("snapshot")
    updated["hub"]["version"] = "2.3.0"
    fake_transport.update_status = UpdateStatus("2.3.0", "2.3.0", False, "Up to date")
    fake_transport.drop()
    fake_transport.restore(Snapshot.from_json(updated))
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(ENTITY)
    assert state.state == "off"
    assert state.attributes["installed_version"] == "2.3.0"
    assert state.attributes["latest_version"] == "2.3.0"
    # Three checks: on add, after the install (Home Assistant refreshes a polled
    # entity after a service call) and after the Hub came back with a new version.
    assert [c[0] for c in fake_transport.calls].count("update_check") == 3


async def test_up_to_date_and_errors(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fake_transport.update_status = UpdateStatus("2.2.0", None, False, "Up to date")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(ENTITY)
    assert state.state == "off"
    assert state.attributes["latest_version"] == "2.2.0"

    fake_transport.update_status = UpdateStatus("2.2.0", None, True, "Something newer")
    fake_transport.errors["update_check"] = HarmonyNgConnectionError("down")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=25))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "off"

    del fake_transport.errors["update_check"]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=50))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == "unknown"
    assert state.attributes["latest_version"] is None
    assert state.attributes["message"] == "Something newer"


async def test_failed_check_retried(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_transport: FakeTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A check that fails, as right after the Hub boots, is retried soon, logged once."""
    fake_transport.errors["update_check"] = HarmonyNgConnectionError("no reply")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    def checks() -> int:
        return [c[0] for c in fake_transport.calls].count("update_check")

    assert hass.states.get(ENTITY).state == "unknown"
    assert checks() == 1

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert checks() == 2
    assert caplog.text.count("release check failed") == 1

    del fake_transport.errors["update_check"]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=32))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert checks() == 3
    assert hass.states.get(ENTITY).state == "on"
    assert "release check works again" in caplog.text

    # Once it works, no more retries until the daily check
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=2))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert checks() == 3


async def test_check_after_reconnect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    """The Hub may have restarted: check again when it comes back."""
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c[0] for c in fake_transport.calls].count("update_check") == 1
    fake_transport.drop()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "unavailable"
    fake_transport.restore()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c[0] for c in fake_transport.calls].count("update_check") == 2
    assert hass.states.get(ENTITY).state == "on"


async def test_retry_cancelled_on_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    fake_transport.errors["update_check"] = HarmonyNgConnectionError("no reply")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c[0] for c in fake_transport.calls].count("update_check") == 1
