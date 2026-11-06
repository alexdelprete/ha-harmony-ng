# Implementation specification for the Harmony NG integration and pyharmonyng

Version 1.0, 2026-11-06. Companion to `docs/HA_INTEGRATION_ARCHITECTURE.md` (the design and its reasoning) and to
`docs/HA_INTEGRATION_FIRMWARE_SPEC.md` (what the firmware provides). This document pins what the
integration and its library implement, entity by entity and call by call, so that the two
transports produce identical results and the firmware side knows which flag unlocks what.

## 0. Scope and delivery

Two components, one repository for now:

- **pyharmonyng**, a typed asyncio client for the Hub's REST and WebSocket API. No Home Assistant
  imports, its own tests replaying the fixtures the firmware repository records. During the
  implementation it lives vendored inside the integration at
  `custom_components/harmony_ng/pyharmonyng/`, so Home Assistant can import it without a PyPI
  release; its tests live in `tests/pyharmonyng/`. At the end of the implementation it moves to
  its own repository and to PyPI (the name was free on 2026-11-06), the vendored copy is deleted
  and `manifest.json` pins the released version. The package keeps the discipline of a separate
  library from day one: no imports from the integration, relative imports only inside the package.
- **ha-harmony-ng**, this repository: the custom integration, including the MQTT transport, which
  is Home Assistant specific and therefore not in the library.

Milestones, each one pull request per repository, aligned with the firmware ones:

<!-- pyml disable md013 -->

| Milestone | Needs firmware | Content |
| --- | --- | --- |
| L1 library 0.1 | milestone 1 fixtures | REST models, WebSocket listener, exceptions, capability helpers, fixture replay tests; vendored in the integration |
| I1 integration 0.1 | milestone 1 on the Hub (milestone 2 for discovery) | API transport, config flow with zeroconf, all first-release entities, services, repairs, diagnostics, quality scale rules except the MQTT-specific ones |
| I2 integration 0.2 | milestone 3 | MQTT transport, transport step in the config flow, transport switch in reconfigure, parity tests, orphaned discovery entity repair |
| I3 integration 0.3 | milestone 1 (capture), milestone 3 (MQTT actions) | Update entity, infrared receiver, child devices with a remote per configured device |

<!-- pyml enable md013 -->

Rules that apply throughout: the repository's CLAUDE.md (pre-commit before every commit, tests in
CI only, 97 percent coverage, `translations/en.json` as the string source, no `strings.json`);
Home Assistant minimum 2026.8.0; Python 3.14; no personal data in fixtures or docs.

## 1. Library: pyharmonyng

### 1.1 Layout

```text
custom_components/harmony_ng/pyharmonyng/   (moves to its own repository at the end)
  __init__.py        public exports and __version__
  client.py          HarmonyNgClient (REST)
  listener.py        HarmonyNgListener (WebSocket)
  models.py          frozen dataclasses
  events.py          event parsing into models
  exceptions.py
  capabilities.py    flag names and MIN_API_VERSION
  py.typed
tests/pyharmonyng/
  fixtures/          copied from the firmware repository tests/fixtures/ha
  test_client.py, test_listener.py, test_models.py, test_events.py
```

Requires Python 3.13 or newer, `aiohttp` only. Strict typing (ty in this repository, mypy strict
once it has its own), `py.typed` shipped. Semantic versions; once released, the integration pins
an exact version in `manifest.json`. While vendored, `ApiTransport` imports it relatively.

### 1.2 Client

```python
class HarmonyNgClient:
    def __init__(self, host: str, session: aiohttp.ClientSession, *, port: int = 8089,
                 token: str | None = None, request_timeout: float = 10.0) -> None: ...
    async def get_status(self) -> HubStatus
    async def get_inventory(self) -> Inventory          # devices with command names only
    async def get_activities(self) -> tuple[Activity, ...]
    async def get_activity_state(self) -> ActivityState
    async def get_rf_status(self) -> RfStatus
    async def get_bt_status(self) -> BtStatus
    async def start_activity(self, activity_id: str) -> None
    async def power_off(self) -> None
    async def cancel_activity(self) -> None
    async def send_command(self, device_id: str, command: str, *,
                           port: int | None = None, repeats: int = 1) -> None   # one tap
    async def ir_raw(self, frequency: int, timings: Sequence[int], *, port: int = 7,
                     repeats: int = 1) -> None
    async def bt_key(self, key: str, *, action: KeyAction = KeyAction.TAP,
                     target: str | None = None) -> None
    async def rf_wake(self, slot: int) -> None
    async def rf_sleep(self, slot: int) -> None
    async def push_config(self) -> None                  # "sync remotes"
    async def activity_help(self) -> HelpResult
    async def activity_help_answer(self, device_id: str, *, on: bool) -> None
```

- Press, hold and release are not on the REST API (`/api/ir-send` sends a tap); they go through
  the listener's `send_command`, which uses the WebSocket `cmdAction` field.
- The session is injected and never closed by the library (Platinum `inject-websession`).
- Every call maps HTTP errors to exceptions (1.5). A `409` becomes `HarmonyNgBusyError`. A `401`
  or `403` becomes `HarmonyNgAuthError`. Connection and timeout errors become
  `HarmonyNgConnectionError`. Any other non-2xx, or a 2xx body whose `ok` or `success` is false,
  becomes `HarmonyNgApiError` with the Hub's `error` string and the status code.
- `get_status` raises `HarmonyNgUnsupportedError` when the reply has no `hub_id` or an `api_version`
  below `MIN_API_VERSION` (firmware before milestone 1) and exposes `HubStatus.capabilities` as a
  frozenset of strings.
- No retries in the library. The coordinator decides.

### 1.3 Listener

```python
class HarmonyNgListener:
    def __init__(self, host: str, session: aiohttp.ClientSession, *, port: int = 8089,
                 token: str | None = None, on_event: Callable[[HubEvent], None],
                 on_connection: Callable[[bool], None],
                 on_snapshot: Callable[[Snapshot], None] | None = None) -> None: ...
    async def start(self) -> Snapshot        # connects, returns the first snapshot
    async def stop(self) -> None
    async def request_snapshot(self) -> Snapshot
    async def send_action(self, action: str, **fields) -> Mapping[str, Any]   # awaits the ack
    async def start_activity(self, activity_id: str) -> None
    async def power_off(self) -> None
    async def cancel_activity(self) -> None
    async def send_command(self, device_id: str, command: str, *,
                           action: CommandAction = CommandAction.TAP) -> None
    async def bt_key(self, key: str, *, action: KeyAction = KeyAction.TAP,
                     target: str | None = None) -> None
    @property
    def connected(self) -> bool
    @property
    def last_seq(self) -> int
```

- Connects to `ws://host:port/ws?token=...` when a token is set, otherwise without the query.
- The first frame must be a `snapshot`; anything else is a protocol error that closes the socket.
- Every subsequent frame is parsed by `events.parse` into a `HubEvent` subclass
  (`ActivityStateEvent`, `ActivityProgressEvent`, `ConfigChangedEvent`, `BtStatusEvent`,
  `RfStatusEvent`, `ButtonEvent`) or ignored with a debug log when unknown.
- Reconnects on any error with backoff 1, 2, 4, 8, 16, 30 s, forever, until `stop`. After a
  reconnect it compares the new snapshot's `seq` with `last_seq` and sets
  `Snapshot.gap = True` when events were missed, so the coordinator refetches inventory.
- Answers server pings (aiohttp does) and treats 45 s of silence as a dead socket (the server
  pings every 30 s).
- `on_connection(False)` fires on loss, `on_connection(True)` after the snapshot of a reconnect,
  which is delivered through `on_snapshot` (as is any unsolicited snapshot the Hub sends).
- Requests over the socket carry a `msgId`; the matching acknowledgement resolves them. An
  acknowledgement with `ok` false raises `HarmonyNgBusyError` when its error mentions busy,
  otherwise `HarmonyNgApiError`; no acknowledgement within 10 s raises `HarmonyNgConnectionError`.
  Pending requests fail when the socket drops.

### 1.4 Models

Frozen dataclasses with `from_json` classmethods; unknown keys ignored, missing optional keys
default to `None` so an older firmware never raises in parsing:

`HubStatus` (hub_id, hub_name, version, api_version, capabilities, auth_enabled, uptime_sec,
legacy_enabled, mdns_enabled, mqtt: MqttInfo | None), `ActivityState` (activity_id, state:
ActivityStatus enum idle, starting, running, stopping, busy, sending), `Activity` (id, name,
type, order), `Device` (id, name, type, manufacturer, model, control_port, commands:
tuple[str, ...]), `Inventory` (devices, version), `RfSlot` (slot, active, remote_id, model,
has_screen, battery_percent, charging, voltage_mv, config_version, hub_config_version, in_sync,
sw_version, last_seen_s), `RfStatus` (running, connected, pairing_active, slots), `BtHost` (bdaddr,
name, connected), `BtStatus` (running, connected, target, hosts), `ButtonEvent` (slot, button,
action, device_id, command, ts), `Snapshot` (hub, activity_state, bt_status, rf_status,
config_files: Mapping[str, int], seq, gap), `HelpResult`.

### 1.5 Exceptions and capabilities

```python
class HarmonyNgError(Exception)
class HarmonyNgConnectionError(HarmonyNgError)
class HarmonyNgAuthError(HarmonyNgError)
class HarmonyNgBusyError(HarmonyNgError)
class HarmonyNgApiError(HarmonyNgError)        # .code, .message
class HarmonyNgUnsupportedError(HarmonyNgError)  # firmware too old
```

`capabilities.py` defines the flag names of the firmware spec as constants and `MIN_API_VERSION =
2`. Firmware version strings are never compared; they are shown to the user only. Release numbers
belong to upstream, so a gate on them would break on the fork.

### 1.6 Tests

Fixtures are the JSON and NDJSON files recorded by the firmware repository (its spec, section 7).
`test_client.py` serves them from an aiohttp test server and checks every model; `test_listener.py`
replays `ws_activity_switch.ndjson` and the other frame files through a test WebSocket and checks
the event sequence, the gap detection and the reconnect backoff with a fake clock. Coverage 100
percent on `models.py` and `events.py`, 95 percent overall.

## 2. Integration

### 2.1 Layout

```text
custom_components/harmony_ng/
  __init__.py        setup, unload, migration, services registration call
  config_flow.py     user, zeroconf, auth, transport, reauth, reconfigure, options
  const.py           DOMAIN, VERSION, keys, capability names, MIN_API_VERSION
  coordinator.py     HarmonyNgCoordinator, HubState
  entity.py          HarmonyNgEntity base, device helpers, remote identity migration
  transport/
    __init__.py      HarmonyNgTransport protocol, TransportEvent
    api.py           ApiTransport (pyharmonyng)
    mqtt.py          MqttTransport (homeassistant.components.mqtt)
  remote.py select.py sensor.py binary_sensor.py button.py event.py infrared.py
  services.py        integration-level services
  repairs.py         issue creation and fix flows
  diagnostics.py
  icons.json translations/en.json quality_scale.yaml manifest.json services.yaml
  brand/             icon and logo
tests/               one module per source module, snapshot tests per platform, fixtures/
```

`manifest.json`: `integration_type` `hub`, `iot_class` `local_push`, `requirements`
`["pyharmonyng==0.1.0"]`, `after_dependencies` `["mqtt"]`, `zeroconf`
`[{"type": "_harmony-ng._tcp.local."}]`, `quality_scale` `platinum`, `version` as per CLAUDE.md.

### 2.2 Transport interface

```python
class HarmonyNgTransport(Protocol):
    capabilities: frozenset[str]
    hub_id: str
    async def connect(self) -> Snapshot
    async def disconnect(self) -> None
    async def fetch_inventory(self) -> Inventory
    async def fetch_activities(self) -> tuple[Activity, ...]
    async def start_activity(self, activity_id: str) -> None
    async def power_off(self) -> None
    async def cancel_activity(self) -> None
    async def send_command(self, device_id: str, command: str, action: CommandAction, repeats: int) -> None
    async def ir_send(self, device_id: str, command: str, port: int, repeats: int) -> None
    async def ir_raw(self, frequency: int, timings: Sequence[int], port: int, repeats: int) -> None
    async def bt_key(self, key: str, action: KeyAction, target: str | None) -> None
    async def rf_wake(self, slot: int) -> None
    async def rf_sleep(self, slot: int) -> None
    async def push_config(self) -> None
    async def activity_help(self) -> HelpResult
    async def activity_help_answer(self, device_id: str, on: bool) -> None
    async def update_check(self) -> UpdateStatus
    async def update_apply(self) -> None
    async def ir_capture(self, enabled: bool) -> None
    def set_callbacks(self, on_event: Callable[[HubEvent], None], on_connection: Callable[[bool], None]) -> None
```

Both implementations raise the library exceptions, so the coordinator and the entities never
know which transport is active.

**ApiTransport** wraps `HarmonyNgClient` and `HarmonyNgListener` with the session from
`async_get_clientsession`. `connect` validates the status (hub id, version, capabilities), starts
the listener and returns its snapshot.

**MqttTransport** uses `homeassistant.components.mqtt`:

- Requires the MQTT integration to be set up (`async_wait_for_mqtt_client`), otherwise raises
  `HarmonyNgConnectionError` and the entry goes to `ConfigEntryNotReady`.
- Subscribes to `<base>/status`, `hub`, `activity_state`, `progress`, `bt`, `rf`, `config`,
  `inventory/#`, `remote/+/button`, `cmd/response`.
- `connect` waits up to 10 s for the retained `hub`, `activity_state`, `bt` and `rf` payloads and builds
  the snapshot from them; `hub` must carry `mqtt_v2` in its capabilities, otherwise
  `HarmonyNgUnsupportedError`; a Hub whose `status` is `offline` raises `HarmonyNgConnectionError`
  so setup retries.
- The `status` topic is the liveness signal: `offline` fires `on_connection(False)`, a later
  `online` rebuilds a snapshot from the retained topics and fires `on_snapshot` then
  `on_connection(True)`. A changed `inventory_version` on the `config` topic is delivered as a
  `ConfigChangedEvent` for devices and activities, so the coordinator refetches.
- `activity_help` and `activity_help_answer` are `cmd` actions too, and `ir_send` is
  `send_command` with a `port` field; the firmware spec lists them.
- Inventory: the retained index plus one chunk per listed device; `fetch_inventory` resolves when
  every chunk with the index's `inventory_version` has arrived (10 s timeout).
- Commands publish to `<base>/cmd` with a uuid4 `id` and await the matching `cmd/response` for
  10 s; `ok: false` maps `code` 409 to `HarmonyNgBusyError`, 401 to `HarmonyNgAuthError`, anything
  else to `HarmonyNgApiError`; a timeout is `HarmonyNgConnectionError`.
- `<base>/status` `offline` or a lost broker connection fires `on_connection(False)`.
- Retained state payloads are converted with the same `events.parse` as the WebSocket frames, so
  both transports feed identical `HubEvent` objects into the coordinator.

### 2.3 Coordinator and state

`HarmonyNgCoordinator(DataUpdateCoordinator[HubState])` with `update_interval=None`.

```python
@dataclass(frozen=True)
class HubState:
    hub: HubStatus
    activity: ActivityState
    activities: tuple[Activity, ...]
    inventory: Inventory
    rf: RfStatus
    bt: BtStatus
    last_activity_id: str | None
    last_button: ButtonEvent | None
    connected: bool
    received_at: datetime
```

- `_async_setup`: `transport.connect()`, then `fetch_activities` and `fetch_inventory`, build the
  first `HubState`. Exceptions map: `HarmonyNgAuthError` to `ConfigEntryAuthFailed`,
  `HarmonyNgUnsupportedError` to `ConfigEntryNotReady` plus the `firmware_too_old` repair, anything
  else to `ConfigEntryNotReady`. No manual logging of these.
- Every `HubEvent` produces a new `HubState` through `async_set_updated_data`. `ConfigChangedEvent`
  with `activities` or `devices` in `files`, and a reconnect snapshot with `gap`, schedule a refetch
  of activities and inventory (debounced 2 s).
- `on_connection(False)` sets `connected=False` and reports the loss through
  `async_set_update_error`, so every entity turns unavailable and Home Assistant logs the loss
  once; the snapshot of the reconnect restores the state through `async_set_updated_data`, which
  logs the recovery (`log-when-unavailable`, no manual logging).
- `last_activity_id` is kept across power off for the remote entity's `last_activity` attribute
  and the `previous activity` option.
- Button events are not state: the coordinator fans them out to per-slot listeners that the
  event entities register in `async_added_to_hass`.
- When a remote's unit id first appears, the coordinator re-keys the device and entity registry
  entries (2.6) and schedules a reload of the entry so the live entities pick up the new keys.

### 2.4 Capability handling

<!-- pyml disable md013 -->

| Condition | Behaviour |
| --- | --- |
| `hub_id` missing or `api_version` below 2 | setup fails with `ConfigEntryNotReady`; repair `firmware_too_old` bound to the entry, showing the version string seen and the firmware milestone needed |
| `ir_raw` absent | the three infrared entities are registered and unavailable |
| `rf_wake` absent | the wake buttons are registered and unavailable |
| `mqtt_v2` absent on an MQTT entry | setup fails as above with repair `mqtt_unsupported` |
| `legacy` present and `legacy_enabled` true | repair `legacy_enabled` (informational): the core Harmony integration sees the same Hub, entities may exist twice |
| remote `remote_id` absent | the remote device is keyed by slot (2.6) until the id arrives |

<!-- pyml enable md013 -->

Capabilities are read once at connect. A capability never removes an entity: entities missing
their feature stay registered and unavailable, as the architecture doc requires.

### 2.5 Config flow

Entry data: `host`, `port`, `token` (optional), `transport` (`api` or `mqtt`), `mqtt_base_topic`
(MQTT only). Entry unique id: `hub_id`. Entry title: the Hub name from the status. Options:
`default_activity` (an activity name or `previous`), `delay_secs` (float, default 0.4). Version 1.

<!-- pyml disable md013 -->

| Step | Shown when | Fields | Validation and errors |
| --- | --- | --- | --- |
| `user` | manual start | `host`, `port` (default 8089) | status call without token; `cannot_connect`, `not_harmony_ng` (no `hub_id`), `unsupported_firmware`; then `auth` or `transport` |
| `zeroconf` | mDNS record found | none | reads TXT `id`, `name`, `auth`, `mqtt`, `topic`, `ver`; sets unique id `id`; `_abort_if_unique_id_configured(updates={host, port})` updates a known Hub's address; `unsupported_firmware` abort when TXT `api` is below the minimum; then `confirm` |
| `confirm` | discovery | none, shows name and host | continues to `auth` when TXT `auth` is `1`, else `transport` |
| `auth` | the Hub reports `auth_enabled` | `token` | status call with the token; `invalid_auth` |
| `transport` | always, I2 onwards (I1 stores `api` silently) | `transport` select, `mqtt_base_topic` visible only for MQTT, prefilled from TXT or status | MQTT: `mqtt_not_configured` when the MQTT integration is absent, `mqtt_unsupported` when the retained `hub` lacks `mqtt_v2` or does not arrive in 10 s, `hub_mismatch` when its `hub_id` differs |
| `reauth_confirm` | `ConfigEntryAuthFailed` | `token` | as `auth`, then `async_update_reload_and_abort` |
| `reconfigure` | user request | `host`, `port`, `token`, `transport`, `mqtt_base_topic` | validates as above against the same `hub_id`; `hub_mismatch` otherwise; `async_update_reload_and_abort` |
| options | user request | `default_activity`, `delay_secs` | `OptionsFlowWithReload`; activity list from the coordinator |

<!-- pyml enable md013 -->

Abort reasons translated by core (`already_configured`, `already_in_progress`,
`reauth_successful`, `reconfigure_successful`) are not duplicated in `en.json`. Every form result
passes `step_id`. The transport is never implied by how the Hub was found.

### 2.6 Devices and identity

<!-- pyml disable md013 -->

| Device | Identifiers | Fields | Notes |
| --- | --- | --- | --- |
| Hub | `(DOMAIN, hub_id)` | manufacturer Logitech, model Harmony Hub, model_id from `skin` when exposed, sw_version `version`, hw_version Logitech base firmware, serial_number `hub_id`, configuration_url `http://host:8089` (API) or absent (MQTT) | root device of the entry |
| Remote | `(DOMAIN, remote_id)` | manufacturer Logitech, model from the slot (`Harmony Ultimate`, `Harmony Elite`, ...), sw_version remote firmware, serial_number `remote_id`, via_device_id the Hub's registry id | one per active slot; the slot number is an attribute of its entities |
| Remote without id | `(DOMAIN, f"{hub_id}:slot{n}")` | as above, no serial | fallback for a remote running firmware that does not report its unit id |
| Configured device | `(DOMAIN, f"{hub_id}:device:{id}")`, a child device (`ChildDeviceInfo`, parent = the Hub's registry id) | name from the inventory | one per inventory device, added as the inventory changes; removable from the device page once it left the inventory |

<!-- pyml enable md013 -->

Identity migration: when an `RfStatusEvent` first carries `remote_id` for a slot whose device
exists under the fallback identifier, `entity.py` updates the device's identifiers and every
entity unique id of that slot from `{hub_id}:slot{n}` to `{remote_id}` through the device and
entity registries, once, before the state is applied. A slot that becomes inactive leaves its
device in place (`stale-devices`: the user removes it through the device page, which the
integration allows via `async_remove_config_entry_device` when the slot is not active).

### 2.7 Entity catalogue

All entities set `has_entity_name=True`, take `translation_key` = key, use the coordinator, and are
unavailable while `connected` is false. Unique id = `{owner_id}_{key}` where `owner_id` is `hub_id`
or `remote_id` (or its fallback). Per-Bluetooth-host entities use `{hub_id}_bt_host_{bdaddr}` with
the address lowercased and colons removed.

<!-- pyml disable md013 -->

| Platform | Key | Owner | Category | Device class / options | Value and attributes | Availability beyond connected |
| --- | --- | --- | --- | --- | --- | --- |
| remote | `remote` (name None) | Hub | none | `RemoteEntityFeature.ACTIVITY` | `is_on` = activity not `-1`; attributes `current_activity` (name), `activity_list`, `last_activity`, `activity_starting`, `devices_list`; `turn_on` with `activity` by name or id, else the default activity; `turn_off` = power off; `send_command` runs each command as press, hold `hold_secs`, release, `num_repeats` times, `delay_secs` between | always |
| select | `activity` | Hub | none | options `power_off` plus activity names | current activity; selecting `power_off` powers off | always |
| sensor | `activity_state` | Hub | diagnostic | enum `idle`, `starting`, `running`, `stopping` | `ActivityState.state` | always |
| sensor | `firmware` | Hub | diagnostic | none | `version` | always |
| sensor | `uptime` | Hub | diagnostic, disabled | timestamp | `received_at - uptime_sec` | always |
| binary_sensor | `busy` | Hub | diagnostic | running | `busy or sending` | always |
| binary_sensor | `bt_host_{bdaddr}` | Hub | diagnostic | connectivity | host connected; attributes `name`, `bdaddr` | created and removed dynamically with the paired host list |
| button | `power_off` | Hub | none | none | power off | always |
| button | `sync_remotes` | Hub | config | none | push config | always |
| button | `cancel_activity` | Hub | config | none | cancel | always |
| sensor | `battery` | Remote | diagnostic | battery, percent | `battery_percent` | slot active |
| sensor | `battery_voltage` | Remote | diagnostic, disabled | voltage, mV | `voltage_mv` | slot active |
| binary_sensor | `charging` | Remote | diagnostic | battery_charging | `charging` | slot active |
| binary_sensor | `config_out_of_sync` | Remote | diagnostic | problem | `not in_sync` | slot active |
| button | `wake` | Remote | config | none | `rf_wake(slot)` | `rf_wake` capability |
| button | `sleep` | Remote | config | none | `rf_sleep(slot)` | slot active |
| event | `button` | Remote | none | event types `press`, `release`; device class button | fired on `ButtonEvent` for the slot; attributes `button`, `device_id`, `command`, `source` | slot active |
| infrared | `ir_front`, `ir_jack1`, `ir_jack2` | Hub | none | emitter; jacks disabled by default | `InfraredEmitterEntity.async_send_command`: `ir_raw(command.modulation, command.get_raw_timings(), port, command.repeat_count)` with port 1, 2, 4 | `ir_raw` capability |
| infrared | `ir_receiver` | Hub | none | receiver; disabled by default | turns the Hub's capture on in `async_added_to_hass` and off on removal; every `ir_received` event becomes `InfraredReceivedSignal(timings, modulation)` | `ir_capture` capability |
| update | `firmware_update` | Hub | config | firmware; `INSTALL` | installed = `hub.version`; latest from the Hub's release check, polled every 24 h and run on add, after an install and when the Hub comes back with a new version; `install` calls `update_apply` | always |
| remote | `remote` of each configured device | child device | none | assumed state, no activity feature | `send_command` without naming the device; `turn_on` sends PowerOn else PowerToggle, `turn_off` PowerOff else PowerToggle; attributes commands, manufacturer, model, type | device still in the inventory |

<!-- pyml enable md013 -->

`parallel_updates`: 0 on sensor, binary_sensor and event; 1 on remote, select, button and
infrared, because the Hub serialises commands and a 409 would otherwise surface as an error.

### 2.8 Services

Entity services on the remote entity, registered in `async_setup_entry` of the remote platform
with `async_register_platform_entity_service`: `remote.send_command` and `remote.turn_on` /
`turn_off` as in core, plus `harmony_ng.sync` (push config to the remotes).

Integration services, registered in `async_setup` (`action-setup`), all with a `device_id`
selector resolving to one Hub entry, raising `ServiceValidationError` for a bad target and
`HomeAssistantError` with a translation key for Hub errors (`action-exceptions`):

<!-- pyml disable md013 -->

| Service | Fields | Behaviour |
| --- | --- | --- |
| `harmony_ng.ir_send` | `device` (inventory device name or id), `command`, `port` (`front`, `jack1`, `jack2`, `all`; default all), `repeats` (1 to 10) | `transport.ir_send`; a command name not in the inventory raises `ServiceValidationError` |
| `harmony_ng.bt_key` | `key`, `action` (`tap`, `press`, `release`), `target` (optional bdaddr) | `transport.bt_key` |
| `harmony_ng.activity_help` | none | returns the Help result as response data (devices and the question asked) |
| `harmony_ng.activity_help_answer` | `device`, `on` | answers one device of the last Help |
| `harmony_ng.activity_cancel` | none | cancel |

<!-- pyml enable md013 -->

`services.yaml` documents every field; `en.json` holds the names, descriptions and the exception
messages (`exception-translations`).

### 2.9 Repairs and diagnostics

<!-- pyml disable md013 -->

| Issue id | Severity | Fixable | Trigger and content |
| --- | --- | --- | --- |
| `firmware_too_old` | error | no | status without `hub_id` or version below the minimum; placeholders version and minimum; cleared on a successful setup |
| `mqtt_unsupported` | error | no | MQTT entry whose retained `hub` lacks `mqtt_v2` |
| `legacy_enabled` | warning | no | the Hub reports `legacy_enabled`; explains the duplicate entity risk with the core integration |
| `mqtt_discovery_orphans` | warning | yes | an `mqtt` device still holds the Hub's old discovery entities (recognised by the `_ir_devices` and `_ir_commands` unique id suffixes the old firmware used together); the fix flow names the devices and removes them with their entities on confirm |

<!-- pyml enable md013 -->

Issues are created with the entry's id and refreshed with `async_refresh_issues` on every setup.

Diagnostics return the entry data with `host`, `token` and `mqtt_base_topic` redacted, the options,
the last `HubState` as a dict with Bluetooth addresses redacted, the transport name, the
capabilities, and the mDNS record when the entry was discovered.

### 2.10 Base entity and naming

`HarmonyNgEntity(CoordinatorEntity[HarmonyNgCoordinator])` holds the owner device, the key and the
unique id, implements `async_entity_id_changed` for in-place entity id changes, and exposes
`available` as `coordinator.last_update_success and self._owner_available()`. Names come from
`translations/en.json` `entity.<platform>.<key>.name`; the remote entity has `name=None`. Icons
live in `icons.json` per key, with state icons for `activity_state`, `charging` and
`config_out_of_sync`.

## 3. Quality scale mapping

The tier is self-declared; `quality_scale.yaml` tracks every rule and `manifest.json` declares the
highest tier with every rule done or exempt: `silver` until discovery lands with firmware
milestone 2, then `platinum`, since the Gold and Platinum rules are already met in code. The
non-obvious ones:

<!-- pyml disable md013 -->

| Rule | Where it is satisfied |
| --- | --- |
| `appropriate-polling` | no polling: `update_interval=None`, push through events; exempt comment says so |
| `test-before-configure`, `test-before-setup` | status call in every flow step; `_async_setup` of the coordinator |
| `unique-config-entry` | unique id `hub_id` on every path |
| `entity-event-setup` | callbacks registered in `async_added_to_hass`, removed in `async_will_remove_from_hass` (event entity, Bluetooth host entities) |
| `action-setup`, `action-exceptions` | 2.8 |
| `entity-unavailable`, `log-when-unavailable` | 2.3; no manual logging |
| `parallel-updates` | 2.7 |
| `reauthentication-flow`, `reconfiguration-flow` | 2.5 |
| `discovery`, `discovery-update-info` | zeroconf step with address update; `todo` until firmware milestone 2 ships, then `done` |
| `dynamic-devices`, `stale-devices` | remote devices appear when a slot activates; Bluetooth host entities follow the paired list; `async_remove_config_entry_device` for inactive slots |
| `entity-category`, `entity-device-class`, `entity-disabled-by-default`, `entity-translations`, `icon-translations`, `exception-translations` | 2.7, 2.8, 2.10 |
| `repair-issues`, `diagnostics` | 2.9 |
| `docs-*` (twelve rules) | README sections in the order the rules list them: description, supported devices, installation, configuration parameters, actions, triggers, conditions, examples, data update, known limitations, troubleshooting, removal; written in I1 |
| `async-dependency`, `strict-typing`, `inject-websession` | pyharmonyng (1.2); the MQTT transport entry is exempt from `inject-websession` with the reason the rule names |

<!-- pyml enable md013 -->

## 4. Tests

- **Fixtures**: the firmware repository's `tests/fixtures/ha/` copied into `tests/fixtures/` of both
  repositories by a script that records the source commit; never hand-edited.
- **Library**: 1.6.
- **Integration**: the library is mocked at the transport boundary with a `FakeTransport` that
  replays fixture events, so tests run without sockets. Per platform a snapshot test of every
  entity's state and attributes after the snapshot and after `ws_activity_switch.ndjson`. Config
  flow tests for every step and error in 2.5, including discovery address update and transport
  switch. Coordinator tests for reconnect, gap refetch and unavailability. Repair tests for each
  issue and the fix flow. Diagnostics snapshot. Services tests for validation and Hub errors.
- **Parity (I2)**: the same fixture sequence is fed through the fake transport and through
  `MqttTransport` on the mocked `mqtt` integration, in one test on the same Home Assistant; every
  entity's registry identity, state and attributes must be identical between the two.
- Coverage 97 percent or higher, enforced by the CI rule in CLAUDE.md.

## 5. Definition of done per milestone

- **L1**: package importable from the integration, strict typing passes, fixtures replay, no
  import of anything outside the package. PyPI publication is deferred to the end of the
  implementation.
- **I1**: every row of 2.7 except the MQTT-only behaviour; flows of 2.5 without the transport
  choice; services, repairs, diagnostics; README sections; `quality_scale.yaml` with every rule
  `done` except `discovery`, `discovery-update-info` (until firmware milestone 2) and the
  MQTT-specific exemptions; coverage 97; verified on the owner's Hub running firmware milestone 1.
- **I2**: MQTT transport, transport step and switch, parity tests, orphan repair; verified with
  firmware milestone 3 against the owner's broker; a transport switch on the live entry keeps every
  entity id and history.
- **I3**: update entity, infrared receiver and child devices, written before the firmware's
  capture item exists; the receiver stays unavailable until the Hub lists `ir_capture`.

## 6. Decisions taken in this document

1. The library owns the WebSocket listener and the reconnect policy; the coordinator only reacts.
2. No retries in the library; `ConfigEntryNotReady` and Home Assistant's own retry handle setup,
   and command errors surface to the user.
3. Inventory in the library carries command names only; raw codes never leave the Hub.
4. MQTT commands time out after 10 s and map `code` to the same exceptions as HTTP status codes.
5. Entity unique ids use the remote's unit id, with a slot fallback and a one-time registry
   migration when the id first appears.
6. The infrared jack entities are disabled by default; the front blaster is enabled.
7. `config_out_of_sync` is the key of the inverted sync sensor, so the problem device class reads
   naturally.
8. `activity_help` returns response data instead of creating entities for the Help dialogue.
9. The `legacy_enabled` repair is informational only; the user decides whether both integrations
   coexist.
10. Options keep the two names core users know, `default_activity` and `delay_secs`, so automations
    port with a rename of the entity id only.
