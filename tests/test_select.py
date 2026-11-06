"""Tests for the activity select."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_frames

ENTITY = "select.living_room_hub_activity"


@pytest.fixture(autouse=True)
def only_select() -> None:
    with patch("custom_components.harmony_ng.PLATFORMS", [Platform.SELECT]):
        yield


async def test_entity(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_select(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_transport: FakeTransport
) -> None:
    state = hass.states.get(ENTITY)
    assert state.state == "PowerOff"
    assert state.attributes["options"] == ["PowerOff", "Watch TV", "Listen to Music"]

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "Watch TV"},
        blocking=True,
    )
    fake_transport.push(load_frames("ws_activity_switch")[0])
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Watch TV"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "PowerOff"},
        blocking=True,
    )
    assert fake_transport.commands() == [("start_activity", ("123456",)), ("power_off", ())]
