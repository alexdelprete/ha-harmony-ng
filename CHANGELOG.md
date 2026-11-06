# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/alexdelprete/ha-harmony-ng/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/alexdelprete/ha-harmony-ng/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alexdelprete/ha-harmony-ng/releases/tag/v0.1.0
