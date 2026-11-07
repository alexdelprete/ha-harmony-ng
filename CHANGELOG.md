# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-11-07

### Added

- Per remote, a "Last battery report" sensor: when the remote last reported its battery, from
  firmware that sends `reported_at`. A battery block the Hub never received (`reported_at`
  null) is unknown, whatever placeholder numbers it carries.
- Last boot uses the Hub's `boot_time` when the firmware sends it. Over MQTT, the Hub status
  the Hub republishes (once its clock is set, on a configuration change) now reaches the
  integration's state instead of waiting for the next reconnect.

### Fixed

- Last boot crept forward: it was the Hub's uptime subtracted from the time of the latest
  event, and the uptime only changes with a snapshot. It is now computed once per snapshot
  when the firmware has no `boot_time`.
- Bluetooth hosts always showed disconnected and the stack not running. The Hub forwards the
  Bluetooth daemon's status file, which has a connected flag per host but no top-level
  `connected` or `running`; the parser required the top-level flag. The connected host is now
  read from the file's `host` entry, whose top-level `target` is the physical remote.
- Firmware update entity: a failed release check stayed unknown for a day, until the next daily
  check. Right after the Hub boots the check can fail before the Hub reaches the internet. A
  failed check is now retried after 15 minutes, the check also runs whenever the Hub reconnects,
  and a failure is logged once.

### Changed

- Remote battery voltage is shown in volts with two decimals ("3.70 V"). In a locale that writes
  a dot as the thousands separator, "3701 mV" read as "3.701 mV". New installs get volts; an
  existing sensor keeps its unit until you change it in the entity settings.
- The Hub's Busy sensor reads "Busy" or "Idle" instead of "Running" or "Not running".

## [0.1.2] - 2026-11-07

### Added

- One button per activity on the Hub, which starts it.
- One button per command on each configured device, disabled by default.

### Fixed

- Bluetooth hosts: the address was read from a key the Hub does not send, so all hosts
  shared an empty address and only one connectivity sensor was created. Each host now gets
  its own sensor; the leftover sensor with the empty address is removed.
- Remote battery, voltage and charging show unknown until the remote's first report,
  instead of the Hub's 0 % placeholder.
- MQTT transport: device and activity types were read from the message type field.
- The link to the Hub's web UI is shown on the MQTT transport too.
- The firmware release check gets up to two minutes to answer, on REST and MQTT alike. The
  Hub retries its downloads, so a check on a slow network outlasted the 10 s request limit.
- The client library is tested against payloads recorded from the firmware.

### Changed

- Remote devices are named and modelled after the product the Hub reports (for example
  "Harmony Ultimate"), with the slot number only when two remotes share a product. The
  device updates in place when the product becomes known; entity ids and names set by the
  user stay as they are.
- Firmware that does not report the product yet names every touchscreen remote `elite`.
  That guess is no longer shown: such a remote is a "Harmony remote" without a model until
  the firmware reports it. Companion and Smart Control remotes keep their names.
- README: the MQTT transport is documented (it shipped in 0.1.0 but was listed as coming
  later), and the event example uses the remote's current entity id.

## [0.1.1] - 2026-11-06

### Fixed

- Brand icon: a compact `h·ng` mark replaces the full wordmark in the square icon, which
  shrank to an unreadable size on the discovery card and in integration lists. The wide
  wordmark stays as the logo.
- Brand images follow the brands image specification: trimmed to the subject, logos at the
  preferred 256 and 512 pixel heights, interlaced and losslessly optimized.

## [0.1.0] - 2026-11-06

First release. Home Assistant integration for a Logitech Harmony Hub running the
open-source [harmony-ng](https://github.com/iranl/harmony-ng) firmware with the
event bus (`api_version` 2 or newer). Requires Home Assistant 2026.11.0 or newer.

### Added

- Config flow with mDNS discovery of `_harmony-ng._tcp`, manual setup by address,
  reauthentication and reconfiguration; optional Personal Access Token when the
  Hub has authentication enabled.
- Two transports: REST and WebSocket (default) with push updates from the Hub's
  event bus, and MQTT through Home Assistant's MQTT integration.
- `remote` entity per Hub with the attributes and services of the core Harmony
  integration (`turn_on` with activity, `turn_off`, `send_command` with device,
  repeats, delay and hold), plus one `remote` per configured device.
- Activity select, activity state, firmware, last-boot and busy sensors; a
  firmware `update` entity that checks the Hub's release once a day.
- Per paired RF remote: battery, voltage, charging and configuration-sync
  sensors, wake and sleep buttons, an `event` entity for key presses.
- Bluetooth hosts as connectivity sensors.
- Infrared emitters for the front blaster and the two emitter jacks, usable by
  Home Assistant's infrared integrations as their transmitter; infrared
  receiver entity, disabled by default, for firmware that supports capture.
- Services: `ir_send`, `bt_key`, `activity_help`, `activity_help_answer`,
  `activity_cancel`, `sync`.
- Device triggers, diagnostics, repair issues for offline Hubs and discovery,
  debug logging from the entry menu, translations in English.
- Vendored `pyharmonyng` client library (REST and WebSocket).
- Harmony NG brand images served by the integration.
- Quality scale `platinum`: every Bronze to Platinum rule done or exempt.

[Unreleased]: https://github.com/alexdelprete/ha-harmony-ng/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/alexdelprete/ha-harmony-ng/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/alexdelprete/ha-harmony-ng/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/alexdelprete/ha-harmony-ng/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alexdelprete/ha-harmony-ng/releases/tag/v0.1.0
