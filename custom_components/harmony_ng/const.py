"""Constants for the Harmony NG integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "harmony_ng"
VERSION = "0.1.10"

MANUFACTURER: Final = "Logitech"
MODEL_HUB: Final = "Harmony Hub"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.INFRARED,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.UPDATE,
]

# Config entry data
CONF_TOKEN: Final = "token"  # noqa: S105
CONF_TRANSPORT: Final = "transport"
CONF_MQTT_BASE_TOPIC: Final = "mqtt_base_topic"
TRANSPORT_API: Final = "api"
TRANSPORT_MQTT: Final = "mqtt"
DEFAULT_PORT: Final = 8089

# Config entry options
CONF_DEFAULT_ACTIVITY: Final = "default_activity"
CONF_DELAY_SECS: Final = "delay_secs"
DEFAULT_DELAY_SECS: Final = 0.4
PREVIOUS_ACTIVITY: Final = "previous"

ZEROCONF_TYPE: Final = "_harmony-ng._tcp.local."
TXT_ID: Final = "id"
TXT_NAME: Final = "name"
TXT_API: Final = "api"
TXT_AUTH: Final = "auth"
TXT_MQTT: Final = "mqtt"
TXT_TOPIC: Final = "topic"

# Repair issues (translations/en.json -> issues)
ISSUE_FIRMWARE_TOO_OLD: Final = "firmware_too_old"
ISSUE_LEGACY_ENABLED: Final = "legacy_enabled"
ISSUE_MQTT_UNSUPPORTED: Final = "mqtt_unsupported"
ISSUE_MQTT_DISCOVERY_ORPHANS: Final = "mqtt_discovery_orphans"

# Services
SERVICE_IR_SEND: Final = "ir_send"
SERVICE_BT_KEY: Final = "bt_key"
SERVICE_ACTIVITY_HELP: Final = "activity_help"
SERVICE_ACTIVITY_HELP_ANSWER: Final = "activity_help_answer"
SERVICE_ACTIVITY_CANCEL: Final = "activity_cancel"
SERVICE_SYNC: Final = "sync"

ATTR_DEVICE: Final = "device"
ATTR_COMMAND: Final = "command"
ATTR_PORT: Final = "port"
ATTR_REPEATS: Final = "repeats"
ATTR_KEY: Final = "key"
ATTR_ACTION: Final = "action"
ATTR_TARGET: Final = "target"
ATTR_ON: Final = "on"

IR_PORTS: Final = {"front": 1, "jack1": 2, "jack2": 4, "all": 7}
MAX_REPEATS: Final = 10

# Remote entity labels that match the core Harmony integration
POWER_OFF_LABEL: Final = "PowerOff"

# Infrared emitter entities, one per output
IR_EMITTERS: Final = {"ir_front": 1, "ir_jack1": 2, "ir_jack2": 4}

RELEASE_URL: Final = "https://github.com/iranl/harmony-ng/releases"
UPDATE_CHECK_INTERVAL_HOURS: Final = 24

# Child devices: configured IR and Bluetooth devices of the Hub
DEVICE_IDENTIFIER_PREFIX: Final = "device"
