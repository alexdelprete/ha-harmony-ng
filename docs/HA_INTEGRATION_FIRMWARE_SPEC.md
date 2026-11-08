<!-- Copy of docs/HA_INTEGRATION_FIRMWARE_SPEC.md in the harmony-ng firmware repository, which is the
     source of truth. Update both together. -->

# Firmware specification for the Harmony NG Home Assistant integration

Version 1.0, 2026-11-06. Companion to the integration's architecture document
(`docs/HA_INTEGRATION_ARCHITECTURE.md` in the ha-harmony-ng repository), which holds the reasoning and the
measurements. This document holds only what the firmware must do, item by item, so that an
implementer can work through it without the design discussion.

## 0. How to use this document

### 0.1 Delivery model

- The work is split into four milestones. **Each milestone is one branch and one pull request on
  the fork** (`alexdelprete/harmony-ng`). The PR is self-reviewed, tested on the Hub and merged into
  the fork's `main` by the author. Nothing goes to the upstream repository until the whole spec and
  the Home Assistant integration work together; at that point the four PRs are opened upstream
  as they are, in order.
- Inside a milestone, commit per numbered item (`feat(events): ...`, `feat(ws): ...`), in the
  order given, so the PR reads as a sequence of small reviewable steps. Conventional commit style
  as in the repository history.
- Before starting a milestone: `git fetch upstream && git merge --ff-only upstream/main` on the
  fork's `main`, then branch from it. Milestone N+1 branches from `main` after milestone N merged.
- Fork branches that are still open upstream and that the integration needs are merged into the
  milestone 1 branch first, as their own commits: `feat/rf-wake` (#81, `POST /api/rf/wake`),
  `feat/bt-state-single-source` (#76) and `fix/bt-multi-host-reconnect` (#84). If upstream merges
  them meanwhile, the merge is a no-op.
- Every item lists its tests. A milestone is done when every item's tests pass on the host build,
  the cross build succeeds for both targets, the Hub verification steps passed on real hardware, and
  `docs/API.md` and `docs/openapi.yaml` describe the new surface.

### 0.2 Rules

- Read `.agents/rules/embedded_devices.md` before touching the Hub. Kill with `-9`, one process on
  `/dev/rfspi`, no `head`, `tail` or `grep -E` on the devices.
- All new daemon code lives inside `hub_daemon`. No new binaries: a static MIPS binary costs about
  100 KB of flash for its libc copy, code inside `hub_daemon` costs 1 to 2 KB per 100 lines, and
  `/data` has 1.7 MB free.
- Nothing new writes flash at runtime. Only user settings persist, through the existing
  `config_store` paths.
- Push paths and the new listeners run on the main `select()` loop, never on the eight HTTP worker
  threads, which refuse a ninth request.
- New threads only where this document says so.
- cJSON for all JSON, `-Os -s`, no new library dependencies.
- Keep the web UIs working. Where a change affects them (WebSocket auth, discovery topics), the
  legacy UI (`android-app`) and the new UI (`frontend`) are part of the item.
- Private data stays out of the repository: no Hub addresses, device names, tokens or captured
  configurations in commits, tests or fixtures. Fixtures come from the host build's sample config.
- Back up the Hub before every deploy and follow the deploy procedure in the private handoff notes.
  Deploys, activity switches, IR sends and Bluetooth actions on the live Hub are coordinated with the
  owner, not run on initiative.

### 0.3 Versioning and compatibility

- The fork does not bump `HARMONY_VERSION`: release numbers belong to upstream, which sets them
  when it merges, and a fork-side bump would collide with upstream's own releases. The integration
  gates on `api_version` and on the capability list, never on a version string or a commit. Where
  this document needs to name a firmware level it says milestone 1 to 4.
- `api_version` is an integer in `GET /api/status`. It is `2` from milestone 1 on and only changes
  on a breaking change to an existing endpoint or message. Additions are announced through
  `capabilities` instead.
- Existing endpoints and WebSocket messages keep their shape. New fields are added, nothing is
  renamed or removed, with the one exception called out in milestone 3 (MQTT discovery entities).

## 1. What the integration consumes

The integration binds one transport per config entry, API (REST plus WebSocket) or MQTT, and expects
the same information on both. This table is the contract. Everything in it is specified in detail in
the milestones.

<!-- pyml disable md013 -->

| Need | API transport | MQTT transport | Milestone |
| --- | --- | --- | --- |
| Identity, version, capabilities | `GET /api/status` fields `hub_id`, `version`, `api_version`, `capabilities` | retained `<base>/hub` | 1, 3 |
| Activity state and busy flag, pushed on every transition | `activity_state` WebSocket event | retained `<base>/activity_state` | 1, 3 |
| Activity progress | `activity_progress` event (exists) | `<base>/progress` (exists) | 1, 3 |
| Inventory and activities | `GET /api/inventory`, `GET /api/activities` (exist) | retained `<base>/inventory/index` and `<base>/inventory/<deviceId>` | 1, 3 |
| Config change notice | `config_changed` event | `<base>/config` | 1, 3 |
| Bluetooth hosts | `bt_status` event, `GET /api/bt-status` | retained `<base>/bt` | 1, 3 |
| RF remotes: unit id, battery, charging, sync, model | `rf_status` event, `GET /api/rf/status` | retained `<base>/rf` | 1, 3 |
| Remote button press and release | `button` event | `<base>/remote/<slot>/button`, QoS 1 | 1, 3 |
| Full state on connect | `snapshot` message | retained topics | 1, 3 |
| Start, stop, cancel activity; send command with press, hold, release; Bluetooth key; sync; remote wake and sleep | existing REST and WebSocket actions | `<base>/cmd` with correlation id, reply on `<base>/cmd/response` | 1, 3 |
| Raw infrared send | `POST /api/ir-raw` | `<base>/ir/raw` | 1, 3 |
| Raw infrared capture | `POST /api/ir-capture`, `ir_received` event | `cmd` action `ir_capture`, `<base>/ir/received` | 1, 3 |
| Firmware update check and install | `GET /api/update-status`, `POST /api/update-check`, `POST /api/update-apply` (exist) | `cmd` actions `update_check` and `update_apply` | 3 |
| Authentication | PAT or Bearer on REST and on the WebSocket upgrade | broker credentials | 1 |
| Liveness | server WebSocket ping every 30 s | LWT on `<base>/status` (exists) | 1 |
| Discovery | mDNS `_harmony-ng._tcp` with TXT record | same record | 2 |
| Core Harmony integration on the same Hub | Logitech protocol on port 8088, off by default, plus SSDP | not applicable | 4 |

<!-- pyml enable md013 -->

## 2. Conventions used by every item

### 2.1 Hub identity

`hub_id` is the Hub's factory unit id, the serial number Logitech wrote into the manufacturing
partition. It is unique per unit, survives every reflash, and is what the stock firmware's HAL
reports as `serial_number`.

Where it is: the MTD partition named `mfg` (`mtd6` on the Hub, 64 KB; find it by name in
`/proc/mtd`, as `payload/scripts/rcS.local` already does for `hw_ver`). At offset `0x9000` there is
an 8-byte magic followed by records, each a 4-byte big-endian length and that many bytes, alternating
key and value: `unitid` (21 characters, 14 hex digits, a dash, 6 hex digits), `arch`, `skin`,
`usb_vendor_id`, `usb_product_id`, `hw_ver`, `key`, then a certificate. Only `unitid` is needed.
The reader scans the records for the key rather than assuming a fixed offset and stops at the
first record with an implausible length.

Rules:

- Read once at daemon start, keep in memory, never write it anywhere. `hub_id` is the `unitid`
  value exactly as stored, trimmed. It is the only name for this value in the API; there is no
  separate serial number field.
- Fallback, only when the partition cannot be read or has no `unitid` (host build, test harness):
  the MAC of the Wi-Fi interface (`ath0`) without separators, 12 lowercase hex characters, and a
  warning in the log. The harness takes `--mfg-file <path>` (or `HARMONY_MFG_FILE`) so tests feed a
  synthetic blob with a fake unit id; `tests/test_mfg.c` builds such a blob and checks the parser,
  including a blob without the key and a truncated one.
- `/data/harmony/hub_id` is not used: nothing in the firmware creates it (it is a leftover entry in
  the backup list from the Codex era) and the file does not exist on a migrated Hub.
- The value is present in `GET /api/status`, the WebSocket `snapshot`, the mDNS TXT record and the
  retained MQTT `hub` topic. It is the only identifier the integration uses for the device registry
  and for entity unique ids, so it must never change for a given unit.

**Remote identity.** Each RF remote has its own unit id in its own `mfg` partition (mtd9 on the
Ultimate, same record layout, same `unitid` key, for example a value of the form
`20141001120000-000002`). It is exposed as `remote_id` per slot in the RF status (3.13) and is the
identifier the integration uses for the remote's device, with the slot number as an attribute only.
Two remotes on one Hub therefore give one `hub_id` and two distinct `remote_id` values, and a
remote re-paired into the other slot keeps its device and history. The name `remote_id` is used only
for this hardware id; the Logitech cloud account number that the legacy protocol calls
`activeRemoteId` is never called that.

### 2.2 Capability flags

`capabilities` is a JSON array of strings in `GET /api/status`, the `snapshot` message, the retained
`hub` topic and (abbreviated) the mDNS TXT record. A flag is present when the feature is compiled in
and working on this firmware, independent of settings. Flags introduced by this document:

<!-- pyml disable md013 -->

| Flag | Meaning | Milestone |
| --- | --- | --- |
| `events` | The event bus exists; `activity_state`, `config_changed`, `bt_status`, `rf_status` and `button` events are pushed over the WebSocket | 1 |
| `snapshot` | A `snapshot` message is sent after the WebSocket upgrade and on `get_snapshot` | 1 |
| `ws_auth` | The WebSocket upgrade honours PAT and Bearer tokens when auth is enabled | 1 |
| `ws_keepalive` | The server pings WebSocket clients and reaps dead ones | 1 |
| `ir_raw` | `POST /api/ir-raw` exists | 1 |
| `rf_wake` | `POST /api/rf/wake` exists (already on the fork, PR #81) | 1 |
| `ir_capture` | `POST /api/ir-capture` and the `ir_received` event exist (3.15) | 1 |
| `mdns` | The mDNS responder is compiled in | 2 |
| `mqtt_v2` | The MQTT layer publishes the retained state topics and the command channel of milestone 3 | 3 |
| `legacy` | The Logitech protocol shim is compiled in; whether it is enabled is a setting | 4 |

<!-- pyml enable md013 -->

### 2.3 JSON and errors

- All timestamps are Unix seconds as JSON numbers, key `ts`.
- Every pushed message and every retained MQTT state payload carries `"type"`, as the existing
  WebSocket messages do.
- Request errors use the existing shapes: HTTP 400 with `{"ok":false,"error":"..."}` for bad input,
  401 when auth is required and missing, 409 with `{"ok":false,"error":"busy"}` when the orchestrator
  holds the interlock, 503 when a client limit is reached.
- New endpoints accept JSON bodies only, `Content-Type: application/json`, and answer JSON.

### 2.4 Settings

New settings live in `/data/harmony/config/settings.json` through `config_store`, appear in
`GET /api/settings` and are accepted by `POST /api/settings`, with defaults when absent:

<!-- pyml disable md013 -->

| Key | Type | Default | Milestone |
| --- | --- | --- | --- |
| `mdns_enabled` | bool | true | 2 |
| `legacy_enabled` | bool | false | 4 |

<!-- pyml enable md013 -->

Changing a setting takes effect without a restart.

### 2.5 Tests

- Host build: `tests/run_tests.sh` builds `hub_daemon_test` with `-DTEST_HARNESS=1` and drives it
  over HTTP on port 8999 in dry-run mode. New Python tests follow the existing files in `tests/`
  and are added to the runner. C unit tests follow `tests/test_ir_encoder.c`.
- Every new source file that has pure logic (event bus, mDNS packet builder, legacy config
  generator, legacy framing) gets a C unit test. Every new endpoint or message gets a Python test
  against `hub_daemon_test`.
- `bash build/compile_all.sh` and `bash build/compile_all.sh remote` must succeed before a milestone
  is tested on the Hub.
- CI (`.github/workflows/ci.yml`) must be green on the PR.

### 2.6 Documentation per item

`docs/API.md` gets a section for every new endpoint and message, `docs/openapi.yaml` gets the paths
and schemas, in the same commit as the code.

## 3. Milestone 1, PR 1: event bus and API layer

Goal: every state change the Hub knows about is emitted once and reaches WebSocket clients
immediately; the WebSocket is authenticated and kept alive; a client gets the full state on
connect; raw infrared can be sent; the Hub identifies itself. About 600 to 850 new lines plus tests.

Order of items: 3.1 first, then 3.2 to 3.6 in any order, then 3.7 to 3.14.

### 3.1 Event bus

New `payload/source/hub_events.c` and `hub_events.h`.

```c
typedef enum {
    HUB_EV_ACTIVITY_STATE,
    HUB_EV_ACTIVITY_PROGRESS,
    HUB_EV_CONFIG_CHANGED,
    HUB_EV_BT_STATUS,
    HUB_EV_RF_STATUS,
    HUB_EV_BUTTON,
    HUB_EV_COUNT
} hub_event_type_t;

typedef struct {
    hub_event_type_t type;
    uint32_t seq;        /* monotonically increasing per daemon run, starts at 1 */
    time_t ts;
    cJSON *payload;      /* object; owned by the bus, valid during dispatch only */
} hub_event_t;

typedef void (*hub_event_sink_fn)(const hub_event_t *ev, void *user);

int  hub_events_init(void);
int  hub_events_subscribe(hub_event_sink_fn fn, void *user);   /* up to 4 sinks */
void hub_events_emit(hub_event_type_t type, cJSON *payload);   /* takes ownership; any thread */
void hub_events_dispatch(void);                                 /* main loop only */
const char *hub_event_type_name(hub_event_type_t type);         /* "activity_state", ... */
uint32_t hub_events_last_seq(void);
```

Behaviour:

- `emit` is callable from any thread (HTTP workers, the state watcher thread, the orchestrator on
  the main loop). It appends to a mutex-protected ring of 32 entries and returns. On overflow the
  oldest entry is dropped, a counter is incremented and one line is logged per overflow burst.
- `dispatch` runs on the main `select()` loop once per iteration, after `orch_tick()`. It pops
  every queued event and calls each sink in subscription order. Sinks therefore run
  single-threaded, which is what `ws_broadcast_text` and the MQTT client expect.
- Before calling the sinks, `dispatch` sets `"type"` to the event type name, and adds `"seq"` and
  `"ts"` to the payload. Sinks must not keep the payload pointer.
- The `select()` timeout stays at the orchestrator's 40 ms, so event latency is bounded by it.
- No event is coalesced by the bus. Coalescing, where wanted, is the emitter's job (3.4, 3.5).

Hooks: `hub_events_init()` before `orch_init()` in `hub_daemon.c`; `hub_events_dispatch()` after
`orch_tick()` in the loop.

Tests: `tests/test_hub_events.c`: subscribe two sinks, emit from a second thread, dispatch on the
first, check order, `seq`, `ts`, type names and the overflow counter.

### 3.2 Activity state event

In `orchestrator.c`, wherever the state changes (`IDLE`, `STARTING`, `RUNNING`, `STOPPING`), including
cancel and the dry-run paths, emit `HUB_EV_ACTIVITY_STATE` with this payload. The shape equals the
existing `get_state` reply so that both are parsed by one routine:

```json
{"type":"activity_state","activity":"123456","state":2,"stateName":"running",
 "busy":false,"sending":true,"seq":17,"ts":1762387200}
```

`state` keeps the numeric enum used by the web UIs, `stateName` is the lowercase name, `busy` and
`sending` as in `GET /api/activity`. `activity` is `"-1"` when idle. Also emit once at daemon start
after `orch_init()`, so sinks have a baseline.

`on_orch_progress` in `hub_ws.c` stops broadcasting itself; it emits `HUB_EV_ACTIVITY_PROGRESS` with
the existing `activity_progress` payload, and the WebSocket sink (3.7) sends it. MQTT keeps
receiving it through `hub_mqtt_publish_progress` until milestone 3 replaces that call with a sink.

Tests: extend `tests/test_action_lifecycle.c` or add `tests/test_ws_events.py`: start an activity in
dry run over REST, read the WebSocket, expect `activity_state` starting, `activity_progress` frames,
`activity_state` running, then stopping and idle on power off.

### 3.3 State watcher on the bus

`state_watch.c` (merged upstream as PR #74) keeps its thread and its fingerprinting but no longer
calls `ws_broadcast_text`. It emits `HUB_EV_BT_STATUS`, `HUB_EV_RF_STATUS` and `HUB_EV_CONFIG_CHANGED`
with the same objects it builds today (`bt_status` = the `/api/bt-status` object, `rf_status` = the
`/api/rf/status` object, `config_changed` = `{"files":[...]}`).

Changes to its policy:

- It runs whether or not a WebSocket client is connected, because MQTT (milestone 3) and the legacy
  shim (milestone 4) need the events too. The 1 s file poll is cheap; the RF HTTP poll is removed in
  3.5.
- Baselines are no longer reset when a client connects. The snapshot (3.9) gives a new client the
  current state, so the watcher only ever reports changes.
- `config_changed` payload gains `"ts"` through the bus and keeps `files` with the names
  `devices`, `activities`, `settings`, `remote_map`.

Tests: `tests/test_ws_events.py`: touch the sample `devices.json` of the harness, expect one
`config_changed` with `["devices"]`; write a BT status file in the harness temp dir, expect one
`bt_status`.

### 3.4 Remote button event with press and release

`hub_rf` already posts every physical key to `POST /api/button-press` with `command`, `action`
(`press` or `release`), `source`, `slot` and, when the key is mapped to a device command, `deviceId`.
The handler in `http_api_remotes.c` dispatches to MQTT only and drops releases.

- The handler emits `HUB_EV_BUTTON` for every call, press and release alike, before any MQTT work:

  ```json
  {"type":"button","slot":1,"button":"VolumeUp","action":"press","source":"remote_rf",
   "deviceId":"70321456","command":"VolumeUp","seq":18,"ts":1762387200}
  ```

  `source` is `remote_rf` for a key pressed on the Harmony remote over RF (Hubs on a build from
  before the elite -> remote rename send `elite_rf`).
  `button` is the physical key name as the remote's keymap knows it. `deviceId` and `command` are
  the mapped target when present, otherwise absent. If today's post from `hub_rf` carries only the
  mapped command and not the key name, add the key name to the post (`rf_keymap.c`), since the
  integration's event entity reports the key, not the target.
- The existing MQTT pulse behaviour is unchanged in this milestone and is replaced in 3 (5.6).
- Auto-repeat while a key is held: `hub_rf` enqueues repeated presses; emit only the first press
  and the release, not the repeats. A `repeat` field is not needed.

Tests: `tests/test_ws_events.py`: post press and release to `/api/button-press`, expect two `button`
events in order with the right `action`.

### 3.5 RF status pushed by hub_rf

Replace the 1 s HTTP poll of `127.0.0.1:8092/api/rf/status` in the watcher with a push from
`hub_rf`:

- In `hub_rf` (`rf_main.c`), after any change to a slot's battery report, charging flag, link state,
  pairing state, model identification, firmware version or config sync state, post the full status
  object (the same one `GET /api/rf/status` returns) to `POST /api/rf/status-changed` on the daemon
  port using `http_post_local`, the path `button-press` already uses. Rate-limit to one post per
  second per change burst.
- The daemon handler (`http_api_remotes.c`) accepts the body only from loopback, runs it through the
  watcher's existing fingerprint (dropping `link` counters and `voltage_mv`) and emits
  `HUB_EV_RF_STATUS` when it differs from the last one. Battery `voltage_mv` is still part of the
  payload; it just does not count as a change.
- The watcher stops polling `hub_rf`. The one-time baseline at daemon start is fetched once from
  `hub_rf` so the snapshot is complete before the first push. This reworks the poll that PR #74
  introduced days earlier; the PR description should say why (the poll served only the web UIs,
  the push serves every sink and removes a 1 s timer).
- The loopback-only check must also exempt the call from auth, as `button-press` from `hub_rf`
  must already be; verify and document the rule in `http_server.c`.

Tests: `tests/test_ws_events.py`: post a status object to `/api/rf/status-changed` twice with only
`link` counters differing, expect exactly one `rf_status` event; post one with `battery.percent`
changed, expect a second. The co-simulation test (`tests/test_co_simulation.py`) covers the real
`hub_rf` push through the mock radio.

### 3.6 Hub identity, version and capabilities in status

`GET /api/status` gains:

```json
{"hub_id":"20140101120000-000001","version":"2.2.0","commit":"abc1234","api_version":2,
 "capabilities":["events","snapshot","ws_auth","ws_keepalive","ir_raw","rf_wake"],
 "legacy_enabled":false,"mdns_enabled":true}
```

`firmware` keeps meaning the Logitech base firmware string. `version` and `commit` are
`HARMONY_VERSION` and `HARMONY_COMMIT`, as in `/api/system-info`. `legacy_enabled` and
`mdns_enabled` mirror the settings and are `false` until the milestones that add them. The same
object, minus the memory and MQTT fields, is the `hub` member of the snapshot (3.9).

Tests: `tests/test_status.py`: fields present, `hub_id` equals the unit id of the synthetic mfg
blob the harness was started with, capability list contains the milestone 1 flags.

### 3.7 WebSocket sink for every bus event

`hub_ws.c` subscribes one sink to the bus in `hub_daemon.c` after `ws_server_init()`. The sink
serialises the payload with `cJSON_PrintUnformatted` and calls `ws_broadcast_text`. All six event
types go out as they are. `on_orch_progress` no longer broadcasts directly (3.2).

Flow control: a client whose socket would block is not awaited; the existing partial-send handling
from PR #74 applies, and a client that fails a send is removed. The integration reconciles through
the snapshot on reconnect, so dropped frames for a dead client are acceptable.

Tests: covered by the tests of 3.2 to 3.5.

### 3.8 WebSocket authentication on upgrade

Today `http_server.c` performs the upgrade (`ws_is_upgrade_req`, `ws_handle_upgrade`) before the auth
check, and `docs/API.md` 11.4 documents a `?token=` form that does not exist.

- When auth is enabled, an upgrade request must carry either `Authorization: Bearer <token>` or
  `?token=<token>` in the request line. Both PAT (`pat_...`) and session tokens (`hht_...`) are
  accepted through `http_auth_check_request`. Digest is not supported on the upgrade.
- Missing or invalid credentials: reply `401` with the existing challenge and close. Never upgrade.
- When auth is disabled, behaviour is unchanged.
- The role of the token is recorded on the client slot. User-role tokens may connect and receive
  events and may send `ping`, `get_state`, `get_snapshot`; command actions follow the same
  permission table as the REST equivalents (`http_auth_is_user_role_permitted`).
- Both web UIs pass their session token as `?token=` when opening the WebSocket
  (`android-app` `app_core.js`, `frontend` `connection.js`). Without this the UIs stop updating as
  soon as a user enables auth.
- `docs/API.md` 11.4 is rewritten to match.

Tests: `tests/test_auth.sh` or a new `tests/test_ws_auth.py`: with auth enabled in the harness,
upgrade without a token gets 401; with a PAT in the query string gets 101; with a PAT in the
`Authorization` header gets 101; with a revoked PAT gets 401.

### 3.9 Full state snapshot on connect

Right after a successful upgrade, and whenever a client sends `{"action":"get_snapshot","msgId":N}`,
the daemon sends one frame:

```json
{"type":"snapshot","msgId":N,
 "hub":{"hub_id":"...","hub_name":"...","version":"2.2.0","api_version":2,"capabilities":[...],
        "auth_enabled":false,"uptime_sec":34821,"legacy_enabled":false,"mdns_enabled":true},
 "activity_state":{...},
 "bt_status":{...},
 "rf_status":{...},
 "config":{"files":{"devices":1762387000,"activities":1762387000,"settings":1762380000,
           "remote_map":1762387000}},
 "seq":42,"ts":1762387200}
```

`activity_state`, `bt_status` and `rf_status` are the last payloads emitted on the bus for those
types (the bus keeps the last payload per type for this purpose; add `const cJSON *hub_events_last(type)`
to 3.1). `config.files` holds the mtimes the watcher tracks, so a client can tell whether its cached
inventory is stale. `seq` is the bus sequence at the time of the snapshot: a client that stored the
last `seq` it processed can tell whether it missed anything while disconnected, and refetches
through REST if so.

The snapshot is sent before any other frame for that client. The frame may exceed 4 KB; the sender
must handle a payload larger than the inbound frame buffer (the 4 KB limit applies to inbound frames
only; confirm the outbound path in `ws_server.c` has no such cap).

Tests: `tests/test_ws_events.py`: connect, first frame is `snapshot` with all members; send
`get_snapshot`, get another with the same `msgId`.

### 3.10 Server keepalive and dead-client reaping

In `ws_server.c`:

- Track per client `last_rx` (any frame) and `ping_sent`.
- From the main loop (`ws_server_tick()` called once per loop iteration), send a WebSocket ping
  frame to every client whose `last_rx` is older than 30 s and that has no ping outstanding.
- A client that has not sent anything (pong or other) within 10 s of the ping is removed and its
  socket closed.
- Client pings are still answered with pongs (exists). A pong from the client counts as `last_rx`.

Tests: `tests/test_ws_keepalive.py` with a compile-time override of the intervals for the harness
(`-DWS_PING_INTERVAL_S=2 -DWS_PONG_TIMEOUT_S=1`): a client that answers pings stays connected for
10 s; a client that ignores them is gone within 4 s (`ws_get_clients` count through a debug
endpoint or by observing the socket close).

### 3.11 Raw infrared endpoint

`POST /api/ir-raw`:

```json
{"frequency":38000,"timings":[9000,-4500,560,-560,560,-1690],"port":1,"repeats":1}
```

- `frequency`: carrier in Hz, 0 for unmodulated, otherwise 20000 to 60000. Default 38000 when absent.
- `timings`: microseconds. Two accepted forms: signed (positive mark, negative space, the form Home
  Assistant's `infrared` platform produces) or all-positive alternating starting with a mark. Length
  2 to 2048. Each absolute value 1 to 65535.
- `port`: bitmask as `/api/ir-send` (`1` front blaster, `2` jack 1, `4` jack 2, `7` all). Default 7.
- `repeats`: 1 to 10, default 1. Meaning as in `hw_ir_send_raw`.
- Calls `hw_ir_send_raw(freq, abs_timings, count, ports, repeats)` after converting signed timings
  to the unsigned alternating form the encoder expects (check `ir_encode_raw` for whether it wants
  marks and spaces interleaved; it does today).
- Reply `200 {"ok":true,"count":N,"duration_ms":M}`. `400` on validation errors with the field name
  in `error`. `409 {"ok":false,"error":"busy"}` when another IR transmission is in progress; use the
  same lock `/api/ir-send` uses so the orchestrator and this endpoint never interleave on the I2S
  path.
- The request body may be up to 32 KB (2048 numbers); confirm the HTTP server's body limit.
- Logged at debug level only, never the timings.

Tests: `tests/test_ir_raw.py` against the harness (dry run makes `hw_ir_send_raw` a no-op that
records its arguments; add that recording under `TEST_HARNESS`): signed and unsigned forms give the
same encoder call; validation errors for frequency, length, port and repeats; Hub verification by
sending a known NEC frame to a device and seeing it react.

### 3.12 OpenAPI file and documentation

- Fix the parse error in `docs/openapi.yaml` at line 1206 (the description of
  `/api/activity/help/answer` contains unquoted `"on": false`); quote the description.
- Add paths `/api/ir-raw`, `/api/rf/status-changed` (marked internal), the new status fields, the
  WebSocket messages `activity_state`, `config_changed`, `bt_status`, `rf_status`, `button`,
  `snapshot`, `get_snapshot`, and the auth rule for the upgrade.
- Validate the file with a YAML parser in CI if the workflow does not do it yet.

### 3.13 Remote unit id over RF

Both firmwares change, in the same milestone, so the Hub and remote bundles ship together.

Remote side (`payload/source/remote`, `remote_ui`):

- At start, read `unitid` from the remote's `mfg` partition with the same reader as 2.1 (share
  the parser source file between the two binaries). Fallback when unreadable: an empty string.
- Send it to the Hub in a new application message `RF_MSG_UNIT_ID` (next free type after the ones
  in `docs/HARMONY_RF_PROTOCOL.md`), payload: `payload[0]` = length, `payload[1..]` = the id as
  ASCII, 21 bytes for current hardware, up to 30. Sent right after every `RF_MSG_VERSION_REPORT`,
  so on link up, every 24 hours and before a full config request. The message is ACKed like the
  version report. The capability byte of the version report gets a new bit meaning "sends unit id".
- A Hub that does not ACK the message (older firmware) costs nothing: the remote drops it like
  any unknown frame.

Hub side (`hub_rf`, `rf_main.c`, `rf_state.c`):

- On `RF_MSG_UNIT_ID` for a slot, store the string in memory and in
  `/data/harmony/remote_slot<N>_version.json` next to `version` and `caps` (that file is already
  rewritten only on change, so no extra flash writes), and read it back at start.
- `GET /api/rf/status` gains `slots[].remote_id` (string, absent until the remote has reported it
  since pairing). A change to it counts as a change for the RF status push (3.5).
- Unpairing a slot clears it.

Documentation: the message in `docs/HARMONY_RF_PROTOCOL.md`, the field in `docs/API.md` 7.1 and in
`docs/openapi.yaml`.

Tests: `tests/test_mfg.c` covers the shared parser. `tests/test_co_simulation.py`: the mock remote
sends `RF_MSG_UNIT_ID`, the status shows `remote_id`, a second report with the same value triggers
no push, unpairing clears it. Hub verification: after deploying both bundles, `/api/rf/status`
shows the remote's unit id within a minute of the remote waking; it survives a Hub restart.

### 3.14 Infrared capture

`ir_i2s_capture()` in `ir_i2s.c` already records one signal into a timing string but nothing
exposes it. This item turns it into a capture mode that Home Assistant's infrared receiver entity
uses to learn codes.

- `POST /api/ir-capture` with `{"enabled":true|false}`. While enabled, `hub_daemon` runs the capture
  loop on a thread (one more thread is acceptable here: capture blocks on the I2S RX DMA) and emits
  `HUB_EV_IR_RECEIVED` for every signal, then re-arms. Disabled, the thread exits and the TX handle
  is released. `GET /api/status` reports the state as `"ir_capture": true|false`; it is false at
  every daemon start, never persisted.
- Capture and transmit share the I2S peripheral. While capture is enabled, a send (activity step,
  `ir-send`, `ir-raw`) pauses the capture, sends, and resumes it; a signal arriving during the send
  is lost. Sends therefore never fail because capture is on.
- Event payload:

  ```json
  {"type":"ir_received","modulation":38000,"timings":[9000,-4500,560,-560,560,-1690],"seq":57,"ts":1762387257}
  ```

  `timings` are signed microseconds (positive mark, negative space), at most 2048 values;
  `modulation` is the measured carrier in Hz, or null when the capture path cannot measure it.
  The parser of the captured string (`F...P...S...`) lives in `ir_encoder.c` next to the encoder,
  so both directions share one representation.
- WebSocket action `ir_capture` with `enabled`, acknowledged like the others; the capability flag
  `ir_capture`.
- MQTT (milestone 3): `cmd` action `ir_capture`, and the event on `<base>/ir/received`, not
  retained.

Tests: `tests/test_ir_capture.c` for the string parser with a recorded capture; in the harness,
`ir-capture` toggles a stub that emits a canned event, and `tests/test_ws_events.py` checks the
`ir_received` frame and that the status reflects the toggle. Hub verification: enable capture,
point a remote at the Hub, see the event with a plausible carrier and timings, then send the same
timings back through `ir-raw` and see the device react.

### 3.15 Hub verification for milestone 1

1. Deploy, then with one WebSocket client (`websocat` or a Python script from the devbox):
   snapshot arrives first; start an activity, see `activity_state` and progress; press keys on the
   remote, see `button` press and release; put the remote on the cradle, see `rf_status`; rename an
   activity in the web UI, see `config_changed`.
2. Enable auth, confirm the web UIs still live-update and an unauthenticated upgrade is refused.
3. Leave a client connected for an hour; it must still receive events (keepalive), and
   `/proc/<pid>/status` of `hub_daemon` must show no growth beyond the baseline (908 KB resident).
4. Peak test: 16 WebSocket clients connected during an activity switch; no client dropped, no
   HTTP request refused, resident memory under 1.5 MB.
5. `POST /api/ir-raw` with a captured NEC frame controls the device.

## 4. Milestone 2, PR 2: mDNS discovery

Goal: Home Assistant finds the Hub on the LAN without the user typing an address. About 250 to 350
lines.

### 4.1 Responder

New `payload/source/hub_mdns.c` and `hub_mdns.h`, running on the main loop (one UDP socket added to
the `select()` set, no thread).

- Service type `_harmony-ng._tcp.local.`, port 8089, instance name = `hub_name` from settings
  with characters outside `[A-Za-z0-9 _-]` replaced by `-`, falling back to `Harmony Hub`.
  The responder probes for the instance name before announcing (RFC 6762 section 8.1) and on a
  conflict appends the hub id, so two Hubs both left at the default name still advertise distinct
  instances. Consumers identify a Hub by the TXT `id`, never by the instance name or hostname.
- Hostname `harmony-ng-<hub_id>.local.` with the full unit id, so several Hubs in one house never
  collide, with an A record for the active interface's IPv4 address. No AAAA.
- TXT record keys, in this order: `id=<hub_id>`, `ver=<HARMONY_VERSION>`, `api=<api_version>`,
  `auth=<0|1>`, `mqtt=<0|1>` (MQTT client enabled and configured), `topic=<base topic>` (only when
  `mqtt=1`), `legacy=<0|1>` (milestone 4; emit `0` until then), `name=<hub_name>` (raw, for display).
- Answers queries for the service type (PTR), the instance (SRV, TXT), the hostname (A) and
  `_services._dns-sd._udp.local.` enumeration. Multicast replies to the group, unicast replies when
  the query asks for it (QU bit). Honours known-answer suppression for the PTR record.
- Announces on start (two unsolicited responses, 1 s apart), on IP change (poll the interface every
  10 s, same routine `/api/network-status` uses) and on any change of a TXT value (hub_name, auth,
  MQTT settings, legacy setting). Sends a goodbye (TTL 0) on clean shutdown.
- TTL 120 s for A and SRV, 4500 s for PTR and TXT.
- Socket: `SO_REUSEADDR`, bind `0.0.0.0:5353`, join `224.0.0.251` on the active interface, multicast
  TTL 255, loopback off. The kernel (2.6.31) has no `SO_REUSEPORT`; nothing else on the Hub listens
  on 5353 today, verify with `netstat -ulnp` before enabling.
- Setting `mdns_enabled` (default true) starts and stops the responder at runtime.

### 4.2 Tests

- `tests/test_mdns_packet.c`: build a query, run it through the packet builder, check the PTR, SRV,
  TXT and A records byte-for-byte against a captured reference, including name compression.
- `tests/test_mdns.py`: with the harness started with `--mdns-port 5354` (test-only flag), send a
  PTR query over loopback and parse the reply; toggle `mdns_enabled` over `POST /api/settings` and
  confirm the port closes.
- Hub verification: `avahi-browse -r _harmony-ng._tcp` from the devbox shows the Hub with all TXT
  keys; renaming the Hub updates the instance name within 5 s; Home Assistant's zeroconf page lists
  the service.

## 5. Milestone 3, PR 3: MQTT rewrite on the bus

Goal: the MQTT layer carries the same information as the WebSocket, publishes on change instead of on
a timer, acknowledges commands, and no longer creates Home Assistant discovery entities. About 800
to 1200 lines, replacing most of `hub_mqtt.c` and all of `hub_mqtt_ha.c` (together about 1540 lines
today), so the net size is flat or smaller.

The transport (`mqtt_client.c`), the settings endpoint `POST /api/mqtt-save`, the 4 KB packet buffer,
the reconnect backoff and the LWT on `<base>/status` stay.

### 5.1 Topic layout

`<base>` is the configured base topic (default `harmony/hub`). All payloads are JSON objects with
`type`, `seq` and `ts` as on the WebSocket.

<!-- pyml disable md013 -->

| Topic | Retained | QoS | Payload |
| --- | --- | --- | --- |
| `<base>/status` | yes | 1 | `online` / `offline` (LWT), unchanged |
| `<base>/hub` | yes | 1 | the `hub` object of the snapshot (3.9) |
| `<base>/activity_state` | yes | 1 | `activity_state` payload |
| `<base>/progress` | no | 0 | `activity_progress` payload |
| `<base>/bt` | yes | 1 | `bt_status` payload |
| `<base>/rf` | yes | 1 | `rf_status` payload |
| `<base>/config` | yes | 1 | `{"type":"config","files":{...mtimes...},"inventory_version":"<hash>"}` |
| `<base>/inventory/index` | yes | 1 | `{"type":"inventory_index","inventory_version":"<hash>","devices":[{"id","name","type","manufacturer","model"}],"activities":[{"id","name","type","order"}]}` |
| `<base>/inventory/<deviceId>` | yes | 1 | `{"type":"inventory_device","id","name","type","manufacturer","model","controlPort","commands":["PowerToggle",...]}` names only, no codes |
| `<base>/remote/<slot>/button` | no | 1 | `button` payload |
| `<base>/cmd` | subscribed | 1 | command request, see 5.3 |
| `<base>/cmd/response` | no | 1 | command reply, see 5.3 |
| `<base>/ir/raw` | subscribed | 1 | same body as `POST /api/ir-raw`, optional `id` for a reply on `cmd/response` |
| `<base>/ir/received` | no | 0 | `ir_received` payload while capture is enabled |

<!-- pyml enable md013 -->

`inventory_version` is a short hash (first 8 hex of SHA-256, `sha256.c` exists) over the device and
activity files. A device chunk is republished only when its own content changed; a removed device
gets an empty retained payload to clear it. The index is published last so a consumer that waits for
the index sees complete chunks.

Each device chunk stays under the 4 KB packet buffer by carrying command names only (202 commands
across 4 devices are about 3 KB of names in total). If a single device exceeds the buffer, split
into `<base>/inventory/<deviceId>/<n>` with `"part":n,"parts":m`; implement the split only if the
sample configuration or the owner's Hub needs it.

### 5.2 Publishing

- One bus sink publishes `activity_state`, `activity_progress`, `bt_status`, `rf_status` and `button`
  to their topics on every event. Retained topics are republished on (re)connect from the bus's last
  payloads, then never on a timer. The 30 s republish is removed.
- `config_changed` triggers a rebuild of `<base>/config` and of the inventory chunks whose source
  changed.
- When the broker is down, events are dropped (as today) and the retained state is resent on
  reconnect; nothing is queued in RAM beyond the client's packet buffer.
- The old state topics `<base>/state`, `<base>/activity`, `<base>/current_activity` and
  `<base>/activity_id` are no longer published; on the first start of the new firmware an empty
  retained payload is published once to each of them so brokers drop the stale values. The new
  JSON topic is named `activity_state`, not `activity`, so a consumer still reading the old name
  gets nothing rather than a payload of a different shape. The release note lists the new topics
  for other MQTT consumers to move to.

### 5.3 Command channel

Subscribe to `<base>/cmd`. Request:

```json
{"id":"c7d1","action":"start_activity","activity":"123456"}
```

`id` is an opaque client string, up to 64 characters, echoed in the reply. Actions and fields mirror
the WebSocket actions exactly: `start_activity` (`activity`), `stop_activity`, `cancel_activity`,
`send_command` (`deviceId`, `command`, `status` = `press`, `hold`, `release` or omitted for a tap,
`repeats`, optional `port` bitmask as `/api/ir-send`), `bt_key` (`key`, `keyAction`, `target`),
`rf_wake` (`slot`), `rf_sleep` (`slot`), `sync`, `get_snapshot` (reply carries the snapshot),
`activity_help` (reply carries `activity` and `toggleDevices` as `POST /api/activity/help`),
`activity_help_answer` (`device`, `on`), `ir_raw` (fields of 3.11), `ir_capture` (`enabled`),
`update_check` (reply carries the fields of `GET /api/update-status` after the check ran) and
`update_apply`.

Reply on `<base>/cmd/response`:

```json
{"type":"cmd_response","id":"c7d1","action":"start_activity","ok":true}
{"type":"cmd_response","id":"c7d1","action":"start_activity","ok":false,"code":409,"error":"busy"}
```

Codes and errors equal the REST ones. A request without `id` is executed and not answered. Malformed
JSON is answered with `code` 400 when an `id` can be recovered, otherwise logged.

No old command topics survive: `<base>/activity/set`, `<base>/send_command`, `<base>/command`
and `<base>/command/#`, `<base>/sync`, `<base>/remote/<n>/sleep`, `<base>/remote/sleep` and
`harmony/ir/pronto` are no longer subscribed. `<base>/cmd` and `<base>/ir/raw` are the only
inbound topics. Pronto over MQTT goes away; the REST endpoint keeps it.

### 5.4 Discovery removal

`hub_mqtt_ha.c` is deleted. On the first start of the new firmware, if the previous version
published discovery configs (detect through a marker file `/data/harmony/mqtt_discovery_done`, or
simply always on first start after upgrade), publish an empty retained payload to every discovery
topic the old code used (`<discovery_prefix>/<component>/<object_id>/config` for the sensors
Activity, Activity ID, IP Address, Firmware, IR Devices, IR Commands, the buttons Power Off, Sync
and the per-slot remote buttons) so Home Assistant removes the orphaned entities, then write the
marker. The exact topic list is taken from `hub_mqtt_ha.c` before deletion and kept in a table in
`hub_mqtt.c`.

The release note of the milestone 3 PR says the Home Assistant integration replaces the discovery entities and
names the integration.

### 5.5 Settings and status

`POST /api/mqtt-save` keeps `enabled`, `host`, `port`, `username`, `password`, `baseTopic` and
`clientId`. The per-slot `slotNRemoteEvents` and `slotNRemoteTopic` fields are removed from the
endpoint, the settings file and both web UIs: button events are always published on
`<base>/remote/<slot>/button`, no custom topics. `GET /api/mqtt-status` and the `mqtt` member of
`/api/status` gain `"v2":true`.

### 5.6 Button events

`<base>/remote/<slot>/button` replaces the pulse-then-zero scheme on `remotes/slotN/Cmd` and the
device button pulse topics. Press and release are two messages, QoS 1, not retained. The device
pulse topics (`<base>/button/device/<cmd>`, the per-device `mqttTopic` and `mqttPulse` fields, the
`POST /api/button-press` MQTT dispatch and the `/api/device-mqtt-test` endpoint) are removed; the
fields are ignored when present in `devices.json` and dropped from the web UI device editor.

### 5.7 Tests

- `tests/test_mqtt_v2.py`: start a small broker on the devbox (`mosquitto` or the Python `amqtt`
  package in the test venv), point the harness at it, and check: retained topics after connect;
  `activity` republished on a dry-run activity start; `inventory/index` and chunks match the sample
  config and change `inventory_version` when a device file is touched; a `cmd` request gets a
  `cmd_response` with the same `id`; a busy start gets 409; `ir/raw` reaches the recorded encoder
  call; the discovery clear publishes empty payloads to the listed topics once.
- `tests/test_mqtt_packets.c` if the chunking logic is non-trivial.
- Hub verification: subscribe with `mosquitto_sub -v -t 'harmony/#'` from the devbox through the
  owner's broker; drive an activity from the remote; confirm the old discovery entities disappear
  from Home Assistant's MQTT integration after the upgrade; check `/proc/<pid>/status` is flat
  after an hour.

## 6. Milestone 4, PR 4: Logitech protocol shim, SSDP and toggle

Goal: with `legacy_enabled` on, Home Assistant's core `harmony` integration (aioharmony 1.0.8) and
other stock clients connect to port 8088, discover the Hub by SSDP, read the configuration, see the
current activity and its changes, start and stop activities and send commands. Off by default.
About 950 to 1400 lines.

The authoritative wire reference is Appendix B, extracted from aioharmony 1.0.8 and from the core
integration's config flow. Where this section and Appendix B disagree, Appendix B wins.

### 6.1 Listener and toggle

- Setting `legacy_enabled`, default false, in `settings.json`, `GET`/`POST /api/settings`, and a
  checkbox "Logitech protocol compatibility (port 8088)" in both web UIs' settings pages.
- When enabled, `hub_daemon` opens a second listener on port 8088 through `http_server_init(8088)`
  added to the main `select()` set. Requests on it go to `hbus_server.c`, never to the `/api/`
  router. Turning the setting off closes the listener and every legacy client.
- Legacy WebSocket clients are tracked by `ws_server.c` in the same table as the 8089 clients, with
  a flag per client marking it legacy so that bus events are formatted differently for them and
  the 8089 broadcasts never reach them. `WS_MAX_CLIENTS` stays 16 in total.
- Port 8088 is never authenticated (the stock protocol has no auth) and the setting's description in
  the UI says so.

### 6.2 TCP probe and provisioning request

- aioharmony first opens a bare TCP connection to 8088 and drops it without sending a byte. The
  listener must accept that and close quietly (the HTTP read timeout handles it; make sure it does
  not log an error per probe).
- `POST /` on 8088 (path exactly `/`, body `{"id ":1,"cmd":"setup.account?getProvisionInfo",
  "params":{}}`, note the key `"id "` with a trailing space, which the parser must tolerate)
  returns:

  ```json
  {"id":1,"code":200,"msg":"OK",
   "data":{"activeRemoteId":"<activeRemoteId>","hubSwVersion":"2.2.0",
           "discoveryServer":"https://svcs.myharmony.com/Discovery/Discovery.svc",
           "hubName":"<hub_name>","accountId":"0","email":""}}
  ```

  `activeRemoteId` is Home Assistant's unique id for the core integration, sent as a string. Use
  the Logitech one when it still exists on the Hub: the stock provisioning file
  `/data/luaworks/provision/preferences` is a JSON object whose `remoteId` member is the 7-digit
  id the Logitech cloud assigned, and the stock `/data` tree survives the harmony-ng install. A
  user who migrates from stock then keeps the core integration's entry and entities without a
  reconfiguration. When the file or the key is absent, derive a stable positive integer from
  `hub_id` (low 31 bits of the SHA-256 of `hub_id`, forced non-zero). Read once at start, never
  written. `discoveryServer` must stay a URL whose host is `svcs.myharmony.com`: aioharmony
  puts its netloc into the WebSocket `domain` query parameter. Never include `ethernetStatus`
  in `data` (it makes Home Assistant report a Hub Pro). `code` is a JSON number. The request is
  sent twice per connect; both get the same reply. HTTP status is ignored by the client, so send
  200 and `Content-Type: application/json`.
- Any other path on 8088 returns 404 except `/description` (6.6).

### 6.3 WebSocket framing

Upgrade on `GET /?domain=svcs.myharmony.com&hubId=<activeRemoteId>`, no `Origin`, no extensions, no
subprotocol. The client pings every 30 s and expects the standard pong within 15 s; `ws_server.c`
already answers pings. The Hub does not need to ping legacy clients, but 3.10 may apply to them
as well.

Every text frame from the client is one JSON object:

```json
{"hubId":"<activeRemoteId>","timeout":5,"hbus":{"cmd":"<mime>?<command>","id":"<uuid>","params":{...}}}
```

A reply is one text frame `{"cmd":"<the request cmd>","id":"<the request id>","code":200,
"msg":"OK","data":{...}}`. The client resolves a request on the first frame whose `id` equals the
request id, whatever else it contains, so a request must get exactly one reply with its id, except
`runactivity` (6.7) and `holdAction` (no reply). `code` is always a JSON number. Unknown commands
get `code` 404, `msg` "Not Found", `data` `{}`.

Notifications (unsolicited) use `"type"` instead of `"cmd"`, no `id`:
`{"type":"connect.stateDigest?notify","data":{...}}`.

### 6.4 Commands

Exact `cmd` strings and the implementation in `hbus_server.c`:

<!-- pyml disable md013 -->

| `cmd` | Params received | Reply `data` and implementation |
| --- | --- | --- |
| `vnd.logitech.harmony/vnd.logitech.harmony.engine?config` | `{"verb":"get","format":"json"}` | the configuration object of 6.5, built on every request by `hbus_config.c`, never cached |
| `vnd.logitech.harmony/vnd.logitech.harmony.engine?getCurrentActivity` | same | `{"result":"<activity id>"}`, `"-1"` when idle, from `orch_get_current_activity()` |
| `harmony.activityengine?runactivity` | `{"async":"true","timestamp":0,"activityId":"<id>"}` | `orch_switch_activity`, or `orch_power_off` for `-1`; sequencing in 6.7 |
| `vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction` | `{"status":"press"|"release","timestamp":"0","verb":"render","action":"<string>"}` | `action` is not valid JSON: `{"command":: "VolumeUp","type":: "IRCommand","deviceId":: "12345678"}`. Replace every `::` with `:` before parsing. `press` and `release` go to the same press, hold and release path as the WebSocket `send_command`. No reply on success; on error reply `{"cmd":...,"id":...,"code":500,"msg":"<reason>"}` within 0.5 s |
| `harmony.engine?changeChannel` | `{"timestamp":0,"channel":"<digits>"}` | send each digit as a command of the running activity's channel device, 200 ms apart; reply `code` 200 with `{}`; 500 when no channel device |
| `setup.sync?None` (literal) | `{"verb":"get","format":"json"}` | reply `code` 200, `{}` |
| `vnd.logitech.connect/vnd.logitech.statedigest?get` | same | the digest object of 6.7 |
| `connect.discoveryinfo?get` | same | `{"friendlyName":"<hub_name>","remoteId":"<activeRemoteId>","hubId":"<hub_id>","current_fw_version":"<version>","protocolVersion":"1.0"}` |
| `setup.account?getProvisionInfo` | never over the WebSocket | not needed |

<!-- pyml enable md013 -->

### 6.5 Stock configuration object

`hbus_config.c` produces the object aioharmony and Home Assistant parse. Only these key paths are
read, and they are the contract; everything else is included for other stock clients and may be
minimal:

- `activity`: array. Each item `id` (string, must convert with `int()`), `label` (string),
  `type`, `activityOrder`, `isTuningDefault` false, `controlGroup` (6.5.1), `sequences` `[]`,
  `fixit` (map of deviceId to `{"id","Power":"On","Input":"","isRelativePower":false,
  "isManualPower":"false"}`), `rules` `[]`. The Power Off activity is present with `id` `"-1"`,
  `label` `"PowerOff"`, `type` `"PowerOff"`: Home Assistant filters it out by label and adds its own.
- `device`: array. Each item `id` (string, `int()`-convertible), `label`, `type`, `manufacturer`,
  `model`, `deviceTypeDisplayName`, `controlGroup` (6.5.1) with every command of the device,
  `isManualPower` `"false"`, `IsKeyboardAssociated` false, `Capabilities` `[]`, `DongleRFID` 0.
- `global`: `{"timeStampHash":"<inventory_version>;<activeRemoteId>","locale":"en-US"}`.
- `content`: `{}`; `sequence`: `[]`.

6.5.1 `controlGroup` is an array of `{"name":"<group>","function":[{"name":"<cmd>","label":"<cmd>",
"action":"{\"command\":\"<cmd>\",\"type\":\"IRCommand\",\"deviceId\":\"<id>\"}"}]}`. `action` is a
JSON-encoded string, valid JSON this time, and the client decodes it and reads `command`. Group
names: `Power`, `Volume`, `Channel`, `NumericBasic`, `TransportBasic`, `NavigationBasic`, other
commands in a group named after the daemon's command category or `Miscellaneous`. For an activity
the groups union the commands of its devices, with the activity's device for each command.

Ids: the client converts activity and device ids with `int()`. The daemon's ids are numeric
strings when migrated from a stock configuration; for an id that is not numeric, `hbus_config.c`
substitutes a stable numeric id (CRC32 of the id, as a string) and `hbus_server.c` maps it back on
`runactivity` and `holdAction`.

### 6.6 SSDP responder and description

New `hub_ssdp.c`, sharing the UDP helpers of `hub_mdns.c`. Active only while `legacy_enabled`.

- Listens on `239.255.255.250:1900`; answers `M-SEARCH` with `ST` `ssdp:all`,
  `upnp:rootdevice` or `urn:myharmony-com:device:harmony:1`. Reply headers: `CACHE-CONTROL:
  max-age=1800`, `EXT:`, `LOCATION: http://<ip>:8088/description`, `SERVER: Linux/2.6 UPnP/1.0
  HarmonyNG/<version>`, `ST` as asked (or the harmony URN for `ssdp:all`),
  `USN: uuid:<uuid>::urn:myharmony-com:device:harmony:1` where `<uuid>` is a UUID v5 derived from
  `hub_id`.
- Sends `NOTIFY ssdp:alive` on enable and every 900 s, `ssdp:byebye` on disable and shutdown.
- `GET /description` on 8088 returns the UPnP device description XML with `deviceType`
  `urn:myharmony-com:device:harmony:1`, `friendlyName` = `hub_name`, `manufacturer` `Logitech`,
  `modelName` `Harmony Hub`, `UDN` `uuid:<uuid>`, `serialNumber` = `hub_id`. Home Assistant's
  matcher needs `deviceType` and `manufacturer` exactly as written; its SSDP flow reads only the
  location host and `friendlyName`, then calls the provisioning POST for the remote id.

### 6.7 State digest and activity start sequencing

The digest object (reply `data` of `statedigest?get` and `data` of every
`connect.stateDigest?notify`):

```json
{"activityId":"123456","activityStatus":1,"configVersion":12,"syncStatus":0,
 "hubSwVersion":"2.2.0","runningActivityList":"123456","stateVersion":1,"sleepTimerId":-1,
 "tzOffset":"0","tzoffset":"0","mode":3,"wifiStatus":1,"updates":{},"hubUpdate":false,
 "contentVersion":0,"accountId":"0","activitySetupState":false,"discoveryServer":
 "https://svcs.myharmony.com/Discovery/Discovery.svc","errorId":0,"errorCode":"200","errorString":"OK",
 "time":1762387200,"sequence":false}
```

The client reads `configVersion`, `syncStatus`, `activityId`, `activityStatus` and `hubSwVersion`.
Rules:

- `configVersion` is a small integer that changes only when `inventory_version` (5.1) changes.
  A changed value makes the client re-fetch the configuration. `syncStatus` is always 0; the client
  ignores a notify with `syncStatus` 1.
- `activityStatus`: 0 idle or powering off, 1 starting, 2 running, 3 stopping. The client acts on
  0 and 1 only; 2 and 3 are sent for other clients.
- `runningActivityList` is the running activity id or `""`.

Sequencing for one `runactivity` request with id M, driven by a bus sink in `hbus_server.c` that
remembers the pending request id per legacy client:

1. Immediately: `{"cmd":"harmony.activityengine?runactivity","id":M,"code":200,"msg":"OK","data":{}}`.
   If the orchestrator refuses (busy, unknown activity): `code` 500, `msg` "Busy" or "Unknown
   activity", and nothing else.
2. On the `activity_state` event `STARTING` (or `STOPPING` for power off): notify
   `{"type":"connect.stateDigest?notify","data":{digest with activityStatus 1 and the target
   activityId}}` to every legacy client (for power off: `activityStatus` 0, `activityId` `"-1"`).
3. Per `activity_progress` step, to the requesting client only:
   `{"cmd":"harmony.engine?startActivity","id":M,"code":100,"msg":"OK","data":{"done":n,"total":m,
   "deviceId":"<id>"}}`.
4. On `RUNNING` (or `IDLE`): to the requesting client
   `{"cmd":"harmony.engine?startActivity","id":M,"code":200,"msg":"OK","data":{}}`. This frame is
   what completes the client's start call; without it the client times out after 60 s.
5. Then to every legacy client: `{"type":"harmony.engine?startActivityFinished","data":
   {"activityId":"<id>","errorCode":"200","errorString":"OK"}}` and a final notify with
   `activityStatus` 2 (or 0 after power off). `startActivityFinished` is what makes the Home
   Assistant entity show the new activity and release its lock.

Activity changes that did not come from a legacy client (remote, web UI, the integration) produce
steps 2 and 5 only. A client must never receive step 4 twice for the same M; the sink drops the
pending id after sending it.

### 6.8 Tests

- `tests/test_hbus_config.c`: build the stock configuration from the sample files and check the key
  paths of Appendix B.4, including the JSON-in-string actions and the `-1` activity.
- `tests/test_hbus.py`: a Python client that speaks the exact frames of Appendix B (provisioning
  POST, WebSocket URL, envelope) against the harness with `legacy_enabled`; covers config, current
  activity, runactivity with the 100 progress, 200 and `startActivityFinished` sequence in dry run,
  holdAction press and release, changeChannel, statedigest get, unknown command 404, and the setting
  toggling the listener.
- `tests/test_hbus_aioharmony.py`: the same scenarios driven by the real `aioharmony==1.0.8` package
  installed in the test venv (`HarmonyAPI(ip_address="127.0.0.1")` needs the port 8088 default, so
  the harness binds 8088 for this test, or the test patches `DEFAULT_WS_HUB_PORT`). This is the test
  that counts: it must pass before the milestone is tried against Home Assistant.
- `tests/test_ssdp.py`: send `M-SEARCH` over loopback (test port flag), parse the reply, fetch
  `/description`, check the fields the core integration matches.
- Hub verification: with the setting on, Home Assistant's core `harmony` integration discovers the
  Hub by SSDP, completes its flow, shows the activities, switches them, sends commands, and follows
  switches made from the remote; with the setting off, the 8088 port is closed and the core
  integration reports unavailable. Both integrations configured on the same Hub at the same time
  must coexist.

## 7. Fixtures for the integration

The Home Assistant library and integration test against recorded frames, not against a Hub. Each
milestone delivers, under `tests/fixtures/ha/`, recorded from the host build with the sample
configuration (no private data):

- Milestone 1: `status.json`, `inventory.json`, `activities.json`, `rf_status.json`, `bt_status.json`,
  `snapshot.json`, and `ws_activity_switch.ndjson` (every frame received by a client during a dry-run
  activity start and power off, one per line), `ws_button.ndjson`, `ws_config_changed.ndjson`,
  `ir_raw_request.json`.
- Milestone 2: `mdns_response.bin` and its decoded `mdns_response.json`.
- Milestone 3: `mqtt_retained.json` (topic to payload after connect), `mqtt_activity_switch.ndjson`
  (topic and payload per line), `mqtt_cmd_response.json`.
- Milestone 4: `hbus_provision.json`, `hbus_config.json`, `hbus_activity_switch.ndjson`,
  `ssdp_response.txt`, `description.xml`.

A fixture is regenerated by a script `tests/record_fixtures.py` so it can be refreshed after a
change, and the script is part of milestone 1.

## 8. Reporting back

At the end of each milestone, record in the PR description: the line count delta, the resident
memory and flash use measured on the Hub (`/proc/<pid>/status`, `df`), the results of the Hub
verification list, and anything in this document that turned out wrong or impossible, with the
change made instead. The integration side is adjusted from that report.

## Appendix A. Event payloads

Reference shapes of the six bus events as sent on the WebSocket and as MQTT payloads. `seq` and
`ts` are added by the bus.

```json
{"type":"activity_state","activity":"123456","state":2,"stateName":"running","busy":false,"sending":false,"seq":1,"ts":0}
{"type":"activity_progress","activity":"123456","activityId":"123456","state":"starting","stateCode":1,"step":2,"currentStep":2,"total":6,"totalSteps":6,"desc":"TV PowerOn","stepDesc":"TV PowerOn","seq":2,"ts":0}
{"type":"config_changed","files":["devices"],"seq":3,"ts":0}
{"type":"bt_status","backend":"btstack","pid":1234,"state":"connecting","target":"11:22:33:44:55:66","remote":{"connected":true,"addr":"11:22:33:44:55:66"},"host":{"connected":true,"addr":"AA:BB:CC:DD:EE:FF","name":"Media Player","pairing":false},"hosts":[{"addr":"AA:BB:CC:DD:EE:01","name":"Television","connected":false,"paired":true,"cid":2},{"addr":"AA:BB:CC:DD:EE:FF","name":"Media Player","connected":true,"paired":true,"cid":6}],"ok":true,"running":true,"connected":true,"pairing":false,"seq":4,"ts":0}
{"type":"rf_status","ok":true,"running":true,"state":"running","connected":true,"pairing_active":false,"paired":true,"slots":[{"slot":1,"active":true,"remote_id":"20141001120000-000002","model":"ultimate","model_name":"Harmony Ultimate","skin":100,"equad_id":16417,"has_screen":true,"battery":{"percent":87,"charging":false,"voltage_mv":3980},"config_version":12,"hub_config_version":12,"in_sync":true,"link":{"last_seen_s":2}}],"seq":5,"ts":0}
{"type":"button","slot":1,"button":"VolumeUp","action":"press","source":"remote_rf","deviceId":"70321456","command":"VolumeUp","seq":6,"ts":0}
```

The `bt_status` object is `hub_btstack`'s status file plus four fields `hub_daemon` adds: `ok`,
`running` (the `hub_btstack` process is alive), `connected` (any host connected) and `pairing`.
Each paired host is an entry of `hosts` keyed by `addr`, with `name`, `connected` and `paired`;
`host` is the host keys go to. `target` and `remote` are the Bluetooth LE remote, not a host, and
`state` is that link's state. There is no `devices` list and no `bdaddr` field (an earlier version
of this appendix showed both).

The `rf_status` slot object is whatever `hub_rf` returns today plus nothing new; `model` is an id
(`ultimate`, `elite`, ..., `unknown`), `model_name` the product name or `null` while unknown. The
fields shown are the ones the integration reads (`slot`, `active`, `remote_id`, `model`, `battery.percent`,
`battery.charging`, `battery.voltage_mv`, `in_sync`, `config_version`, `hub_config_version`). If a
listed field does not exist in `hub_rf`'s status today, add it.

## Appendix B. Logitech protocol as spoken by aioharmony 1.0.8

Extracted from tag v1.0.8 of Harmony-Libs/aioharmony (the package moved there from ehendrix23;
Home Assistant core 2026.9.3 pins `aioharmony==1.0.8`, the development branch 1.0.10). Section 6
is written from this appendix; it is kept so an implementer can check a detail without the source.

### B.1 Connect sequence

1. `asyncio.open_connection(host, 8088)`: a bare TCP connect, dropped without data. Only a refused
   connection makes the client try XMPP instead.
2. `POST http://host:8088/` with headers `Origin: http://sl.dhg.myharmony.com`,
   `Content-Type: application/json`, `Accept: application/json`, `Accept-Charset: utf-8`, body
   `{"id ":1,"cmd":"setup.account?getProvisionInfo","params":{}}`. Reads `data.activeRemoteId`
   (required) and `data.discoveryServer` (its netloc becomes the `domain` query parameter,
   default `svcs.myharmony.com`). HTTP status is ignored; the body must be a JSON object.
3. WebSocket `ws://host:8088/?domain=<netloc>&hubId=<activeRemoteId>`, no Origin header, no
   extensions, no subprotocol, IPv4 only, connect timeout 5 s.
4. In parallel: `statedigest?get`, `config`, a second provisioning POST (same body, `"id "` now a
   uuid), `discoveryinfo?get`, then `getCurrentActivity`. From the second POST it reads `code`
   (200 as number or string), `data.activeRemoteId` (the Home Assistant unique id), `data.hubSwVersion`
   (sw_version), `data.email`, `data.accountId`, and whether `ethernetStatus` is present (model
   "Harmony Hub Pro 2400" when it is).
5. Timeouts: 15 s per command with one retry, 60 s around the whole connect, 240 s around the
   info refresh. A failed config fetch is logged and the connect still succeeds, with no activities.

### B.2 Envelope and matching

Outbound: `{"hubId":"<activeRemoteId>","timeout":5,"hbus":{"cmd":"<mime>?<command>","id":"<uuid4>",
"params":{...}}}`, compact JSON. Default params `{"verb":"get","format":"json"}`.

Inbound keys consulted: `id`, `cmd`, `type`, `code`, `msg`, `data`. A plain request resolves on
the first frame whose `id` equals the request id, regardless of `cmd` or `code`. Notification
handlers match on `type` with a regex and on `data` values with `==` (numbers must be JSON numbers).
`code` must be the number 200 for config, getCurrentActivity, changeChannel, sync and the start
activity completion; `msg` is never compared.

Keepalive: the client sends a WebSocket ping every 30 s and expects a pong within 15 s. On any
error it reconnects after 1 s with backoff doubling to 30 s, forever. A reconnect reuses the cached
remote id and does not refetch state, so the shim should send a digest notify to a client that
reconnects (send one right after every upgrade; it is harmless).

### B.3 Command strings

<!-- pyml disable md013 -->

| Purpose | `cmd` on the wire | params |
| --- | --- | --- |
| configuration | `vnd.logitech.harmony/vnd.logitech.harmony.engine?config` | default |
| current activity | `vnd.logitech.harmony/vnd.logitech.harmony.engine?getCurrentActivity` | default; reads `data.result` as `int()` |
| start or stop activity | `harmony.activityengine?runactivity` | `{"async":"true","timestamp":0,"activityId":"<id>"}`; `"-1"` for power off |
| send command | `vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction` | `{"status":"press","timestamp":"0","verb":"render","action":"{\"command\":: \"VolumeUp\",\"type\":: \"IRCommand\",\"deviceId\":: \"12345678\"}"}`; then the same with `"release"` after the hold delay, each with a new id; no reply expected; a reply with `code` other than 200 within 0.5 s plus the hold is reported as an error |
| change channel | `harmony.engine?changeChannel` | `{"timestamp":0,"channel":"<string>"}`; expects `code` 200 |
| sync | `setup.sync?None` | default; expects `code` 200, then the client refetches everything |
| state digest | `vnd.logitech.connect/vnd.logitech.statedigest?get` | default; reads `data.configVersion`, stores `data` as hub state, `data.hubSwVersion` as firmware |
| discovery info | `connect.discoveryinfo?get` | default; reads `data.friendlyName` |
| provisioning | `setup.account?getProvisionInfo` | HTTP POST only, never on the WebSocket |

<!-- pyml enable md013 -->

### B.4 Configuration key paths read

- `data.activity[]`: `id` (converted with `int()`), `label` (string, lowercased for lookups).
  Home Assistant drops the item whose label is `PowerOff`.
- `data.device[]`: `id` (`int()`), `label`, `controlGroup[].function[].action` (a JSON string,
  decoded, `command` read).
- `data.global.timeStampHash`: only when `activeRemoteId` is missing; the part after the last `;`
  becomes the unique id.
- Not read: `type`, `manufacturer`, `model`, `sequences`, group names.

### B.5 Start activity handlers

All four handlers require the frame's `id` to equal the request id and expire after 300 s:

- `cmd` `harmony.activityengine?runactivity`: a `code` other than 100 or 200 fails the start.
- `cmd` `harmony.engine?startActivity` with `code` 100: progress, logs `data.done` and
  `data.total`.
- `cmd` `harmony.engine?helpdiscretes` with `data.isHelpDiscretes` `"true"`: progress.
- `cmd` `harmony.engine?startActivity` or `helpdiscretes` with `code` 200: success. Any other
  code: failure. The client waits 60 s for this frame.

### B.6 Notifications

Matched on `type`, any or no `id`:

- `connect.stateDigest?notify`: ignored unless `data.configVersion` and `data.syncStatus` exist
  and `syncStatus` is not 1. A changed `configVersion` triggers a full refetch. With
  `data.activityStatus` 1 the client sets the starting activity to `int(data.activityId)`; with 0 it
  sets the current activity to `-1` (power off) unless already off. 2 and 3 are not acted on.
- `harmony.engine?startActivityFinished`: `int(data.activityId)` becomes the current activity;
  this fires the client's new-activity callback, which is what updates Home Assistant's entity and
  releases its activity lock. Without `data` the client sends `getCurrentActivity` instead.

### B.7 Home Assistant core config flow

- manifest `ssdp` matcher: `deviceType` `urn:myharmony-com:device:harmony:1` and `manufacturer`
  `Logitech`. Requirement `aioharmony==1.0.8`, dependency `remote`.
- SSDP step reads the location URL's host and `upnp.friendlyName` (missing name raises), then calls
  the provisioning POST through `HubConnector.get_remote_id()` and uses `str(remote_id)` as the
  unique id. An existing entry with the same host aborts before any network call.
- User step: `HarmonyAPI(ip_address=host)`, `connect()` must return true; unique id
  `str(harmony.hub_id)` from `activeRemoteId`, fallback `timeStampHash`. Entry data stores only
  name and host.
- Device info: sw_version from `hubSwVersion`, model from the presence of `ethernetStatus`.
