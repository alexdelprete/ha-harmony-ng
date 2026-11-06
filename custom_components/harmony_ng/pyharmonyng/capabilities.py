"""Capability flags and the API version the library requires.

The names match the firmware specification. A flag is present in the Hub's
capability list when the feature is compiled in; settings may still disable it.
"""

from __future__ import annotations

from typing import Final

MIN_API_VERSION: Final = 2
"""First `api_version` with the event bus, the snapshot and `hub_id` in the status."""

CAP_EVENTS: Final = "events"
CAP_SNAPSHOT: Final = "snapshot"
CAP_WS_AUTH: Final = "ws_auth"
CAP_WS_KEEPALIVE: Final = "ws_keepalive"
CAP_IR_RAW: Final = "ir_raw"
CAP_RF_WAKE: Final = "rf_wake"
CAP_MDNS: Final = "mdns"
CAP_MQTT_V2: Final = "mqtt_v2"
CAP_LEGACY: Final = "legacy"

ALL_CAPABILITIES: Final = frozenset(
    {
        CAP_EVENTS,
        CAP_SNAPSHOT,
        CAP_WS_AUTH,
        CAP_WS_KEEPALIVE,
        CAP_IR_RAW,
        CAP_RF_WAKE,
        CAP_MDNS,
        CAP_MQTT_V2,
        CAP_LEGACY,
    }
)
