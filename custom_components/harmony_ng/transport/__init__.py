"""Transport abstraction: one entity model, interchangeable backends.

Entities, services and the coordinator never know which transport is active. Both
transports raise the library's exceptions and feed the same event objects.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from custom_components.harmony_ng.pyharmonyng import (
    Activity,
    CommandAction,
    HelpResult,
    HubEvent,
    Inventory,
    KeyAction,
    Snapshot,
    UpdateStatus,
)

type EventCallback = Callable[[HubEvent], None]
type ConnectionCallback = Callable[[bool], None]
type SnapshotCallback = Callable[[Snapshot], None]


class HarmonyNgTransport(Protocol):
    """What the coordinator needs from a backend."""

    name: str
    """`api` or `mqtt`, for diagnostics."""

    @property
    def hub_id(self) -> str | None:
        """Return the Hub id once connected."""

    @property
    def capabilities(self) -> frozenset[str]:
        """Return the capability flags read at connect."""

    @property
    def connected(self) -> bool:
        """Return whether the push channel is up."""

    def set_callbacks(
        self,
        *,
        on_event: EventCallback,
        on_connection: ConnectionCallback,
        on_snapshot: SnapshotCallback,
    ) -> None:
        """Register the coordinator's callbacks before `connect`."""

    def set_token(self, token: str | None) -> None:
        """Use another credential from now on."""

    async def connect(self) -> Snapshot:
        """Validate the Hub, open the push channel and return the first snapshot."""

    async def disconnect(self) -> None:
        """Close everything."""

    async def fetch_inventory(self) -> Inventory:
        """Return every configured device."""

    async def fetch_activities(self) -> tuple[Activity, ...]:
        """Return the configured activities."""

    async def start_activity(self, activity_id: str) -> None:
        """Start an activity."""

    async def power_off(self) -> None:
        """Stop the running activity."""

    async def cancel_activity(self) -> None:
        """Clear a stuck activity change."""

    async def send_command(
        self, device_id: str, command: str, action: CommandAction, repeats: int
    ) -> None:
        """Send a device command as a tap, press, hold or release."""

    async def ir_send(self, device_id: str, command: str, port: int, repeats: int) -> None:
        """Send a device command on given outputs."""

    async def ir_raw(self, frequency: int, timings: Sequence[int], port: int, repeats: int) -> None:
        """Send raw infrared timings."""

    async def bt_key(self, key: str, action: KeyAction, target: str | None) -> None:
        """Send a Bluetooth HID key."""

    async def rf_wake(self, slot: int) -> None:
        """Wake the remote in a slot."""

    async def rf_sleep(self, slot: int) -> None:
        """Put the remote in a slot to sleep."""

    async def push_config(self) -> None:
        """Push the configuration to the remotes."""

    async def activity_help(self) -> HelpResult:
        """Run Help on the current activity."""

    async def activity_help_answer(self, device_id: str, on: bool) -> None:
        """Answer the Help question for one device."""

    async def update_check(self) -> UpdateStatus:
        """Ask the Hub for a release check and return the versions."""

    async def update_apply(self) -> None:
        """Install the available release."""

    async def ir_capture(self, enabled: bool) -> None:
        """Start or stop infrared capture."""
