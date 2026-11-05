# Claude Code Development Guidelines for Harmony NG Integration

## Critical Initial Steps

> **MANDATORY: At the START of EVERY session, you MUST read this entire CLAUDE.md file.**

**At every session start, you MUST:**

1. **Read this entire CLAUDE.md file** for project context and mandatory procedures
1. **Review recent git commits**: `git log --oneline -20`
1. **Check current status**: `git status`

## ⚠️ Editing rules for this file

This CLAUDE.md has two zones, bounded by HTML comment markers containing the
strings `BEGIN SHARED:repo-sync` and `END SHARED:repo-sync` (grep the file to
find their exact positions):

- **Outside the markers**: integration-specific. Edit freely.
- **Between the markers**: auto-generated from `ha-integration-template` via
  `repo-sync.py`. Edits there get overwritten on the next sync. To change
  shared guidance, edit `templates/markers/CLAUDE_SHARED.md.j2` upstream and
  re-sync downstream.

> **Note**: The marker names above are deliberately not written with the full
> `<!-- … -->` HTML syntax. `repo-sync.py` matches that literal pattern when
> deciding where to inject SHARED content, so quoting it here would cause the
> injector to confuse this prose for an actual marker and break the file. See
> the marker injection code in `repo-sync.py::inject_markers` for the regex.

**Before adding generic workflow guidance to this file** (lint commands, release
process, pre-commit invocations, anything that would apply to every integration):

1. Check the SHARED block first.
1. If similar guidance already lives there, do not duplicate it here — refer to
   the SHARED block instead.
1. If it doesn't yet, promote it to `CLAUDE_SHARED.md.j2` in the template repo
   and re-sync. Do not write it as a one-off in this file.

This rule prevents drift between integration-specific copies and the template
source of truth (the kind of drift that, for example, caused `uvx pre-commit`
mentions to survive a template-side change to plain `pre-commit`).

## Project Overview

### What is Harmony NG?

A Home Assistant custom integration for Harmony NG.

### Integration Type

- **Type**: Hub
- **IoT Class**: Local Polling

### File Structure

```text
custom_components/harmony_ng/
├── __init__.py          # Integration setup
├── config_flow.py       # Config flow
├── const.py             # Constants
├── coordinator.py       # Data coordinator
├── sensor.py            # Sensor entities
├── diagnostics.py       # Diagnostics
├── device_trigger.py    # Device triggers
├── helpers.py           # Helper functions
├── repairs.py           # Repair flows
├── manifest.json        # Integration metadata
├── quality_scale.yaml   # Quality scale tracking
├── icons.json           # Entity icons
└── translations/        # Translations
```

## Code Architecture

### Core Components

<!-- TODO: Document each component's responsibilities specific to this integration -->

1. **`__init__.py`** — Integration lifecycle management
   - `async_setup_entry()` — initialize coordinator and platforms
   - `async_unload_entry()` — clean shutdown and resource cleanup
   - `async_migrate_entry()` — config migration logic

1. **`config_flow.py`** — UI configuration
   - ConfigFlow for initial setup
   - OptionsFlowWithReload for runtime options
   - Reconfigure flow for connection settings

1. **`const.py`** — Constants and sensor definitions

1. **`coordinator.py`** — Data update coordination
   - Manages polling cycles and data refresh
   - Error handling and retry logic

1. **`api.py`** — Device communication layer
   <!-- TODO: Document protocol (REST, MQTT, Modbus, Telnet, etc.) and connection management -->

1. **`sensor.py`** — Sensor entity platform

1. **`helpers.py`** — Shared utilities and logging helpers

## Integration-Specific Features

<!-- TODO: Document protocol details, device constants, special values, sensor definitions, etc. -->

## Key Files to Review

<!-- TODO: Update with integration-specific critical files -->

- `const.py` — constants and sensor definitions
- `helpers.py` — shared utilities and logging helpers
- `api.py` — device communication layer
- `sensor.py` — sensor entities
- `CHANGELOG.md` — release history overview
- `docs/releases/` — detailed release notes

## Project-Specific Release Steps

<!-- TODO: Document any extensions to the shared release workflow -->

This project follows the shared release workflow documented below. Add project-specific
release steps here as needed (e.g., specific linting tools, release notes file usage).

## Project-Specific Do's and Don'ts

<!-- TODO: Add integration-specific guidelines beyond the shared ones -->

In addition to the shared Do's and Don'ts below:

**DO:**

- Use `translations/en.json` as the source of truth for all English strings
- (Add integration-specific guidelines here)

**NEVER:**

- Create `strings.json` — it is a Core-only build-time feature, ignored by custom integrations
- (Add integration-specific restrictions here)

<!-- BEGIN SHARED:repo-sync -->
<!-- END SHARED:repo-sync -->

## Reference Documentation

- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
