"""Fixtures for the Harmony NG integration tests.

The integration is exercised against a fake transport that replays the recorded
fixtures, so no socket is opened. The `hass` fixture and the test helpers come from
pytest-homeassistant.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.harmony_ng.const import CONF_TOKEN, CONF_TRANSPORT, DOMAIN, TRANSPORT_API
from custom_components.harmony_ng.pyharmonyng import (
    Activity,
    CommandAction,
    HelpResult,
    Inventory,
    KeyAction,
    Snapshot,
    parse,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .pyharmonyng.conftest import load_frames, load_json

HUB_ID = "20140101120000-000001"
REMOTE_ID = "20141001120000-000002"
HOST = "192.0.2.10"


class FakeTransport:
    """A transport fed by fixtures, recording every command it receives."""

    name = TRANSPORT_API

    def __init__(self) -> None:
        self.snapshot = Snapshot.from_json(load_json("snapshot"))
        self.activities = tuple(
            Activity.from_json(item) for item in load_json("activities")["activities"]
        )
        self.inventory = Inventory.from_json(load_json("inventory"))
        self.help_result = HelpResult.from_json(load_json("help"))
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.errors: dict[str, Exception] = {}
        self.connect_error: Exception | None = None
        self._connected = False
        self.on_event: Any = None
        self.on_connection: Any = None
        self.on_snapshot: Any = None

    @property
    def hub_id(self) -> str | None:
        return self.snapshot.hub.hub_id

    @property
    def capabilities(self) -> frozenset[str]:
        return self.snapshot.hub.capabilities

    @property
    def connected(self) -> bool:
        return self._connected

    def set_callbacks(self, *, on_event: Any, on_connection: Any, on_snapshot: Any) -> None:
        self.on_event = on_event
        self.on_connection = on_connection
        self.on_snapshot = on_snapshot

    def set_token(self, token: str | None) -> None:
        self.calls.append(("set_token", (token,)))

    async def connect(self) -> Snapshot:
        self.calls.append(("connect", ()))
        if self.connect_error is not None:
            raise self.connect_error
        self._connected = True
        return self.snapshot

    async def disconnect(self) -> None:
        self.calls.append(("disconnect", ()))
        self._connected = False

    async def fetch_inventory(self) -> Inventory:
        self._record("fetch_inventory")
        return self.inventory

    async def fetch_activities(self) -> tuple[Activity, ...]:
        self._record("fetch_activities")
        return self.activities

    async def start_activity(self, activity_id: str) -> None:
        self._record("start_activity", activity_id)

    async def power_off(self) -> None:
        self._record("power_off")

    async def cancel_activity(self) -> None:
        self._record("cancel_activity")

    async def send_command(
        self, device_id: str, command: str, action: CommandAction, repeats: int
    ) -> None:
        self._record("send_command", device_id, command, action, repeats)

    async def ir_send(self, device_id: str, command: str, port: int, repeats: int) -> None:
        self._record("ir_send", device_id, command, port, repeats)

    async def ir_raw(self, frequency: int, timings: Sequence[int], port: int, repeats: int) -> None:
        self._record("ir_raw", frequency, list(timings), port, repeats)

    async def bt_key(self, key: str, action: KeyAction, target: str | None) -> None:
        self._record("bt_key", key, action, target)

    async def rf_wake(self, slot: int) -> None:
        self._record("rf_wake", slot)

    async def rf_sleep(self, slot: int) -> None:
        self._record("rf_sleep", slot)

    async def push_config(self) -> None:
        self._record("push_config")

    async def activity_help(self) -> HelpResult:
        self._record("activity_help")
        return self.help_result

    async def activity_help_answer(self, device_id: str, on: bool) -> None:
        self._record("activity_help_answer", device_id, on)

    # Test helpers

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if name in self.errors:
            raise self.errors[name]

    def commands(self) -> list[tuple[str, tuple[Any, ...]]]:
        """Return the recorded calls without the connection bookkeeping."""
        return [
            c
            for c in self.calls
            if c[0]
            not in ("connect", "disconnect", "fetch_inventory", "fetch_activities", "set_token")
        ]

    def push(self, frame: dict[str, Any]) -> None:
        """Deliver one event frame as the Hub would."""
        event = parse(frame)
        assert event is not None
        self.on_event(event)

    def push_frames(self, name: str) -> None:
        """Deliver every frame of an NDJSON fixture."""
        for frame in load_frames(name):
            self.push(frame)

    def drop(self) -> None:
        """Simulate the push channel dropping."""
        self._connected = False
        self.on_connection(False)

    def restore(self, snapshot: Snapshot | None = None, *, gap: bool = False) -> None:
        """Simulate a reconnect with a snapshot."""
        self._connected = True
        self.on_snapshot((snapshot or self.snapshot).with_gap(gap))
        self.on_connection(True)


@pytest.fixture
def fake_transport() -> Generator[FakeTransport]:
    """Replace the real transport with the fake for every entry set up."""
    transport = FakeTransport()
    with patch("custom_components.harmony_ng.build_transport", return_value=transport):
        yield transport


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the fixture Hub on the API transport."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=HUB_ID,
        title="Living Room Hub",
        data={CONF_HOST: HOST, CONF_PORT: 8089, CONF_TOKEN: None, CONF_TRANSPORT: TRANSPORT_API},
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_transport: FakeTransport
) -> MockConfigEntry:
    """Set the integration up on the fake transport."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip the integration setup in config flow tests."""
    with patch("custom_components.harmony_ng.async_setup_entry", return_value=None) as mocked:
        yield mocked
