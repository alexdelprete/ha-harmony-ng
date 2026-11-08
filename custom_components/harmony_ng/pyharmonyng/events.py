"""Events the Hub pushes, parsed from WebSocket frames or MQTT payloads.

Both transports carry the same JSON objects, so one parser serves both.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from .models import (
    ActivityProgress,
    ActivityState,
    BtStatus,
    IrSignal,
    JsonDict,
    RemoteButton,
    RfStatus,
    _int,
    _list,
    _opt_str,
)


@dataclass(frozen=True, slots=True)
class HubEvent:
    """Common header of every pushed event."""

    type: str
    seq: int
    ts: int


@dataclass(frozen=True, slots=True)
class ActivityStateEvent(HubEvent):
    """The orchestrator changed state."""

    state: ActivityState


@dataclass(frozen=True, slots=True)
class ActivityProgressEvent(HubEvent):
    """One step of a start or stop sequence was sent."""

    progress: ActivityProgress


@dataclass(frozen=True, slots=True)
class ConfigChangedEvent(HubEvent):
    """Configuration files changed on the Hub."""

    files: tuple[str, ...]

    @property
    def inventory_changed(self) -> bool:
        """Return whether devices or activities changed."""
        return "devices" in self.files or "activities" in self.files


@dataclass(frozen=True, slots=True)
class BtStatusEvent(HubEvent):
    """The Bluetooth stack or its hosts changed."""

    status: BtStatus


@dataclass(frozen=True, slots=True)
class RfStatusEvent(HubEvent):
    """An RF remote slot changed."""

    status: RfStatus


@dataclass(frozen=True, slots=True)
class ButtonEvent(HubEvent):
    """A key was pressed or released on a remote."""

    button: RemoteButton


@dataclass(frozen=True, slots=True)
class IrReceivedEvent(HubEvent):
    """The Hub captured an infrared signal."""

    signal: IrSignal


@dataclass(frozen=True, slots=True)
class IrCaptureEvent(HubEvent):
    """Infrared capture was turned on or off, or its receiver error changed."""

    enabled: bool
    error: str | None


EVENT_ACTIVITY_STATE: Final = "activity_state"
EVENT_ACTIVITY_PROGRESS: Final = "activity_progress"
EVENT_CONFIG_CHANGED: Final = "config_changed"
EVENT_BT_STATUS: Final = "bt_status"
EVENT_RF_STATUS: Final = "rf_status"
EVENT_BUTTON: Final = "button"
EVENT_IR_RECEIVED: Final = "ir_received"
EVENT_IR_CAPTURE: Final = "ir_capture"


def _activity_state(header: HubEvent, data: JsonDict) -> HubEvent:
    return ActivityStateEvent(
        header.type, header.seq, header.ts, state=ActivityState.from_json(data)
    )


def _activity_progress(header: HubEvent, data: JsonDict) -> HubEvent:
    return ActivityProgressEvent(
        header.type, header.seq, header.ts, progress=ActivityProgress.from_json(data)
    )


def _config_changed(header: HubEvent, data: JsonDict) -> HubEvent:
    return ConfigChangedEvent(
        header.type,
        header.seq,
        header.ts,
        files=tuple(str(name) for name in _list(data, "files")),
    )


def _bt_status(header: HubEvent, data: JsonDict) -> HubEvent:
    return BtStatusEvent(header.type, header.seq, header.ts, status=BtStatus.from_json(data))


def _rf_status(header: HubEvent, data: JsonDict) -> HubEvent:
    return RfStatusEvent(header.type, header.seq, header.ts, status=RfStatus.from_json(data))


def _button(header: HubEvent, data: JsonDict) -> HubEvent:
    return ButtonEvent(header.type, header.seq, header.ts, button=RemoteButton.from_json(data))


def _ir_received(header: HubEvent, data: JsonDict) -> HubEvent:
    return IrReceivedEvent(header.type, header.seq, header.ts, signal=IrSignal.from_json(data))


def _ir_capture(header: HubEvent, data: JsonDict) -> HubEvent:
    return IrCaptureEvent(
        header.type,
        header.seq,
        header.ts,
        enabled=bool(data.get("ir_capture")),
        error=_opt_str(data, "ir_capture_error"),
    )


_PARSERS: Final[Mapping[str, Callable[[HubEvent, JsonDict], HubEvent]]] = {
    EVENT_ACTIVITY_STATE: _activity_state,
    EVENT_ACTIVITY_PROGRESS: _activity_progress,
    EVENT_CONFIG_CHANGED: _config_changed,
    EVENT_BT_STATUS: _bt_status,
    EVENT_RF_STATUS: _rf_status,
    EVENT_BUTTON: _button,
    EVENT_IR_RECEIVED: _ir_received,
    EVENT_IR_CAPTURE: _ir_capture,
}

EVENT_TYPES: Final = frozenset(_PARSERS)


def parse(frame: Mapping[str, Any]) -> HubEvent | None:
    """Return the event a frame carries, or None when it is not an event.

    Acknowledgements, pongs and snapshots are not events; neither is a type this
    library does not know, which a newer firmware may add.
    """
    event_type = frame.get("type")
    if not isinstance(event_type, str):
        return None
    parser = _PARSERS.get(event_type)
    if parser is None:
        return None
    header = HubEvent(event_type, _int(frame, "seq"), _int(frame, "ts"))
    return parser(header, frame)
