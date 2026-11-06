"""REST client for the Harmony NG Hub."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

import aiohttp

from .exceptions import (
    HarmonyNgApiError,
    HarmonyNgAuthError,
    HarmonyNgBusyError,
    HarmonyNgConnectionError,
)
from .models import (
    IR_PORT_ALL,
    Activity,
    ActivityState,
    BtStatus,
    HelpResult,
    HubStatus,
    Inventory,
    KeyAction,
    RfStatus,
)

DEFAULT_PORT: Final = 8089
DEFAULT_TIMEOUT: Final = 10.0

MAX_IR_TIMINGS: Final = 2048
MIN_IR_TIMINGS: Final = 2
MAX_IR_TIMING_US: Final = 65535
MIN_IR_FREQUENCY: Final = 20000
MAX_IR_FREQUENCY: Final = 60000
MAX_IR_REPEATS: Final = 10


def _error_message(data: Any, fallback: str) -> str:
    if isinstance(data, Mapping):
        for key in ("error", "message", "msg"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback


class HarmonyNgClient:
    """Asynchronous REST client.

    The aiohttp session is injected and never closed by the client. Every call maps
    the Hub's answer to a typed model or raises one of the library's exceptions;
    nothing is retried here.
    """

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        port: int = DEFAULT_PORT,
        token: str | None = None,
        request_timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Keep the connection parameters; nothing is sent until a method is called."""
        self._host = host
        self._port = port
        self._session = session
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

    @property
    def host(self) -> str:
        """Return the Hub's host."""
        return self._host

    @property
    def port(self) -> int:
        """Return the Hub's HTTP port."""
        return self._port

    @property
    def base_url(self) -> str:
        """Return the base URL of the REST API."""
        return f"http://{self._host}:{self._port}"

    @property
    def token(self) -> str | None:
        """Return the token in use, if any."""
        return self._token

    def set_token(self, token: str | None) -> None:
        """Replace the token for later calls, for example after a reauthentication."""
        self._token = token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
        try:
            async with self._session.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                params=params,
                headers=headers,
                timeout=self._timeout,
            ) as response:
                status = response.status
                try:
                    data = await response.json(content_type=None)
                except ValueError:
                    data = None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HarmonyNgConnectionError(f"{method} {path}: {err}") from err

        if status in (401, 403):
            raise HarmonyNgAuthError(_error_message(data, "authentication required"))
        if status == 409:
            raise HarmonyNgBusyError(_error_message(data, "the Hub is busy"))
        if status >= 400:
            raise HarmonyNgApiError(_error_message(data, f"HTTP {status}"), code=status)
        if isinstance(data, Mapping) and (data.get("ok") is False or data.get("success") is False):
            raise HarmonyNgApiError(
                _error_message(data, "the Hub refused the request"), code=status
            )
        return data

    async def _get(self, path: str, params: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        data = await self._request("GET", path, params=params)
        return data if isinstance(data, Mapping) else {}

    async def _post(
        self,
        path: str,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        data = await self._request(
            "POST", path, json=json if json is not None else {}, params=params
        )
        return data if isinstance(data, Mapping) else {}

    async def get_status(self) -> HubStatus:
        """Return identity, version and capabilities.

        Raises:
            HarmonyNgUnsupportedError: the firmware predates the API this library
                speaks.
        """
        return HubStatus.from_json(await self._get("/api/status"))

    async def get_inventory(self) -> Inventory:
        """Return every configured device with the names of its commands."""
        return Inventory.from_json(await self._get("/api/inventory"))

    async def get_activities(self) -> tuple[Activity, ...]:
        """Return the configured activities, ordered as the Hub lists them."""
        data = await self._get("/api/activities")
        items = data.get("activities")
        if not isinstance(items, list):
            return ()
        return tuple(Activity.from_json(item) for item in items if isinstance(item, Mapping))

    async def get_activity_state(self) -> ActivityState:
        """Return the current activity and orchestrator state."""
        return ActivityState.from_json(await self._get("/api/activity"))

    async def get_rf_status(self) -> RfStatus:
        """Return the RF subsystem state and the paired remotes."""
        return RfStatus.from_json(await self._get("/api/rf/status"))

    async def get_bt_status(self) -> BtStatus:
        """Return the Bluetooth stack state and the paired hosts."""
        return BtStatus.from_json(await self._get("/api/bt-status"))

    async def start_activity(self, activity_id: str) -> None:
        """Start an activity.

        Raises:
            HarmonyNgBusyError: another activity change is in progress.
        """
        await self._post("/api/activity", {"activity": activity_id})

    async def power_off(self) -> None:
        """Stop the running activity."""
        await self._post("/api/poweroff")

    async def cancel_activity(self) -> None:
        """Clear a stuck activity change and return the orchestrator to idle."""
        await self._post("/api/activity-cancel")

    async def send_command(
        self,
        device_id: str,
        command: str,
        *,
        port: int | None = None,
        repeats: int = 1,
    ) -> None:
        """Send a device command by name, as one tap.

        Press, hold and release go through the WebSocket listener, which is the
        only path the Hub offers for them.
        """
        body: dict[str, Any] = {"deviceId": device_id, "command": command, "repeats": repeats}
        if port is not None:
            body["port"] = port
        await self._post("/api/ir-send", body)

    async def ir_raw(
        self,
        frequency: int,
        timings: Sequence[int],
        *,
        port: int = IR_PORT_ALL,
        repeats: int = 1,
    ) -> None:
        """Send raw infrared timings.

        Args:
            frequency: carrier in Hz, 0 for unmodulated, otherwise 20 to 60 kHz.
            timings: microseconds, signed (positive mark, negative space) or
                all-positive alternating starting with a mark; 2 to 2048 values.
            port: bitmask of outputs, 1 front blaster, 2 jack 1, 4 jack 2.
            repeats: 1 to 10.

        Raises:
            ValueError: an argument is out of the Hub's accepted range.
        """
        if frequency != 0 and not MIN_IR_FREQUENCY <= frequency <= MAX_IR_FREQUENCY:
            raise ValueError(f"frequency {frequency} Hz is outside 20 to 60 kHz")
        if not MIN_IR_TIMINGS <= len(timings) <= MAX_IR_TIMINGS:
            raise ValueError(f"{len(timings)} timings; between 2 and {MAX_IR_TIMINGS} are accepted")
        if any(value == 0 or abs(value) > MAX_IR_TIMING_US for value in timings):
            raise ValueError("every timing must be between 1 and 65535 microseconds")
        if not 1 <= port <= IR_PORT_ALL:
            raise ValueError(f"port mask {port} is outside 1 to {IR_PORT_ALL}")
        if not 1 <= repeats <= MAX_IR_REPEATS:
            raise ValueError(f"repeats {repeats} is outside 1 to {MAX_IR_REPEATS}")
        await self._post(
            "/api/ir-raw",
            {"frequency": frequency, "timings": list(timings), "port": port, "repeats": repeats},
        )

    async def bt_key(
        self, key: str, *, action: KeyAction = KeyAction.TAP, target: str | None = None
    ) -> None:
        """Send a Bluetooth HID key to the connected host, or to `target`."""
        body: dict[str, Any] = {"key": key, "keyAction": action.value}
        if target is not None:
            body["target"] = target
        await self._post("/api/bt-key", body)

    async def rf_wake(self, slot: int) -> None:
        """Wake the remote's screen in that slot."""
        await self._post("/api/rf/wake", params={"slot": str(slot)})

    async def rf_sleep(self, slot: int) -> None:
        """Put the remote in that slot to sleep; slot 0 means every remote."""
        await self._post("/api/rf/sleep", params={"slot": str(slot)})

    async def push_config(self) -> None:
        """Push the configuration to the remotes."""
        await self._post("/api/rf/push-config")

    async def activity_help(self) -> HelpResult:
        """Re-send the running activity's start sequence and list the devices to ask about."""
        return HelpResult.from_json(await self._post("/api/activity/help"))

    async def activity_help_answer(self, device_id: str, *, on: bool) -> None:
        """Answer the Help question for one device: `on` false sends its power toggle."""
        await self._post("/api/activity/help/answer", {"device": device_id, "on": on})
