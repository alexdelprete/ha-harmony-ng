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
