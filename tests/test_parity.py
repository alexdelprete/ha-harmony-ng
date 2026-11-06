"""The API and MQTT transports must produce the same entities from the same Hub."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.harmony_ng.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTransport
from .pyharmonyng.conftest import load_frames
from .test_transport_mqtt import (  # noqa: F401
    BASE,
    flush_timers,
    no_lingering_timers,
    retained_payloads,
    setup_with_retained,
)

VOLATILE = {"uptime", "firmware_update"}


def entity_states(hass: HomeAssistant) -> dict[str, tuple[str, dict[str, Any]]]:
    """Return every Harmony NG entity's state and attributes, without timestamps."""
    registry = er.async_get(hass)
    result = {}
    for entry in registry.entities.values():
        if entry.platform != DOMAIN or entry.translation_key in VOLATILE:
            continue
        state = hass.states.get(entry.entity_id)
        if state is None:
            continue
        # An event entity's state is the time it last fired; only its attributes compare.
        value = "<fired>" if entry.domain == "event" else state.state
        result[entry.entity_id] = (value, dict(state.attributes))
    return result


def registry_entries(hass: HomeAssistant) -> dict[str, tuple[Any, ...]]:
    """Return the registry identity of every Harmony NG entity."""
    registry = er.async_get(hass)
    return {
        entry.entity_id: (
            entry.unique_id,
            entry.translation_key,
            entry.entity_category,
            entry.disabled_by,
        )
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
    }


@pytest.mark.usefixtures("mqtt_mock")
async def test_transports_match(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    fake = FakeTransport()
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.harmony_ng.build_transport", return_value=fake):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        for frame in load_frames("ws_activity_switch")[:5]:
            fake.push(frame)
        fake.push(load_frames("ws_button")[0])
        await hass.async_block_till_done()
        api_states = entity_states(hass)
        api_registry = registry_entries(hass)
        assert len(api_states) > 15
        await hass.config_entries.async_remove(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert not registry_entries(hass)

    mqtt_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=mock_config_entry.unique_id,
        title=mock_config_entry.title,
        data={**mock_config_entry.data, "transport": "mqtt", "mqtt_base_topic": BASE},
    )
    mqtt_entry.add_to_hass(hass)
    await setup_with_retained(hass, mqtt_entry, retained_payloads())
    for frame in load_frames("ws_activity_switch")[:5]:
        topic = "activity_state" if frame["type"] == "activity_state" else "progress"
        async_fire_mqtt_message(hass, f"{BASE}/{topic}", json.dumps(frame))
    async_fire_mqtt_message(
        hass, f"{BASE}/remote/1/button", json.dumps(load_frames("ws_button")[0])
    )
    await hass.async_block_till_done()

    assert registry_entries(hass) == api_registry
    assert entity_states(hass) == api_states
    await flush_timers(hass)
