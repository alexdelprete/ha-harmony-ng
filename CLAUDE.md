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
- **Marketplace categories**: `buttons_remotes` <!-- TODO: pick one to three real categories; the
  known ids are the keys of `integration_category` in core's
  homeassistant/components/homeassistant/strings.json (e.g. `energy.meters_monitoring`) -->

### File Structure

```text
custom_components/harmony_ng/
├── __init__.py          # Integration setup
├── config_flow.py       # Config flow
├── const.py             # Constants
├── coordinator.py       # Data coordinator
├── entity.py            # Base entity (DeviceInfo, entity lifecycle hooks)
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

1. **`entity.py`** — Base entity: unique ids, `DeviceInfo` (hub device or a sub-device linked
   with `via_device_id`), entity lifecycle hooks

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
<!-- Synced by repo-sync on 2026-11-06 -->

<!--
==============================================================================
⚠️  TEMPLATE-MANAGED ZONE — DO NOT EDIT BETWEEN BEGIN SHARED AND END SHARED.

This entire region is auto-generated from
ha-integration-template/templates/markers/CLAUDE_SHARED.md.j2 via
`repo-sync.py`. Edits between the marker lines are silently overwritten
on the next sync.

To change shared guidance:
  1. Edit CLAUDE_SHARED.md.j2 in ha-integration-template
  2. Sync downstream: `python repo-sync.py sync <consumer>`

Integration-specific guidance belongs OUTSIDE the markers (above
BEGIN SHARED or below END SHARED).
==============================================================================
-->

## Context7 for Documentation

Always use Context7 MCP tools automatically (without being asked) when:

- Generating code that uses external libraries
- Providing setup or configuration steps
- Looking up library/API documentation

Use `resolve-library-id` first to get the library ID, then `get-library-docs` to fetch documentation.

## GitHub MCP for Repository Operations

Always use GitHub MCP tools (`mcp__github__*`) for GitHub operations instead of the `gh` CLI:

- **Issues**: `issue_read`, `issue_write`, `list_issues`, `search_issues`, `add_issue_comment`
- **Pull Requests**: `list_pull_requests`, `create_pull_request`, `pull_request_read`, `merge_pull_request`
- **Reviews**: `pull_request_review_write`, `add_comment_to_pending_review`
- **Repositories**: `search_repositories`, `get_file_contents`, `list_branches`, `list_commits`
- **Releases**: `list_releases`, `get_latest_release`, `list_tags`

Benefits over `gh` CLI:

- Direct API access without shell escaping issues
- Structured JSON responses
- Better error handling
- No subprocess overhead

## CI Workflow Status and Logs

> **IMPORTANT**: Always use `gh` CLI for CI workflow status and logs — it's more efficient than GitHub MCP.

The project has 3 CI workflows: **Lint**, **Tests**, and **Validate**.

**List recent workflow runs:**

```bash
gh run list --repo alexdelprete/ha-harmony-ng --limit 5
```

**Get workflow status for a specific run:**

```bash
gh run view <run_id> --repo alexdelprete/ha-harmony-ng
```

**Get test coverage from Tests workflow logs:**

```bash
gh run view <run_id> --repo alexdelprete/ha-harmony-ng --log 2>&1 | grep "TOTAL"
```

**Quick one-liner to get latest Tests run coverage:**

```bash
# Get latest Tests run ID and fetch coverage
gh run list --repo alexdelprete/ha-harmony-ng --limit 5 | grep Tests
# Then use the run ID from the output
gh run view <run_id> --repo alexdelprete/ha-harmony-ng --log 2>&1 | grep "TOTAL"
```

## Coding Standards

### Data Storage Pattern

**DO use `runtime_data`** (modern pattern):

```python
entry.runtime_data = MyData(device_name=name)
```

**DO NOT use `hass.data[DOMAIN]`** (deprecated pattern)

### Translations (Custom Integrations)

Per [HA contributor docs](https://contributors.home-assistant.io/docs/internationalization/custom_integration/):

- **DO use `translations/en.json`** as the source of truth for English strings
- **DO NOT create `strings.json`** — it is a Core-only build-time feature and is ignored by custom integrations
- All translation files go in `translations/<lang>.json` (e.g., `en.json`, `de.json`, `it.json`)

### Logging

Use structured logging:

```python
_LOGGER.debug("Sensor %s subscribed to %s", key, topic)
```

**DO NOT** use f-strings in logger calls (deferred formatting is more efficient)

Use centralized logging helpers from `helpers.py` when available:

- `log_debug(logger, context, message, **kwargs)`
- `log_info(logger, context, message, **kwargs)`
- `log_warning(logger, context, message, **kwargs)`
- `log_error(logger, context, message, **kwargs)`

Always include context parameter (function name). Format: `(function_name) [key=value]: message`

**Never log manually what HA logs automatically:**

- **DataUpdateCoordinator**: Just raise `UpdateFailed` — HA handles logging automatically
- **ConfigEntryNotReady**: HA logs automatically — don't log manually
- This prevents log spam during extended outages

### Error Handling

- Use custom exceptions (not `return False`) for proper entity availability tracking
- Raise exceptions in the API layer and let the coordinator handle retries
- Define integration-specific exceptions (e.g., `ConnectionError`, `DataError`)

### Type Hints

Always use type hints for function signatures.

### Async/Await Conventions

- All coordinator methods are async
- API methods use async/await properly
- Config entry methods follow HA conventions:
  - `async_setup_entry()` / `async_unload_entry()` return `None` and signal failure by raising
    a `ConfigEntry*` exception (core rule since 2026.11; a `return False` still works for custom
    integrations but becomes a generic `ConfigEntryError`). Unload with
    `async_unload_platforms_or_raise()`. Tests patch `async_setup_entry` with `return_value=None`
  - `async_on_unload()` — sync (despite the name)
  - `async_forward_entry_setups()` — async
- Never use blocking calls in async context

## Configuration Best Practices

Following HA best practices, configuration is split between `data` (initial config) and `options` (runtime tuning):

### config_entry.data (changed via Reconfigure flow)

Connection and identity parameters: name, host, port, device ID, etc.

### config_entry.options (changed via Options flow)

Runtime tuning parameters: scan_interval, timeout, etc. Use `OptionsFlowWithReload` for auto-reload
and do **not** also register `entry.add_update_listener()`: a config entry update listener combined
with a reloading flow is deprecated since HA 2026.6 and raises `ValueError` from 2026.12. Either the
flow reloads the entry, or a listener does, never both.

### Config Flow Patterns

- Schemas use `probatio` (Home Assistant's validation engine since 2026.9, `import probatio`, no alias,
  as in core). `import voluptuous as vol` still runs through a runtime alias, but on HA 2026.11 `ty`
  rejects a voluptuous `Schema` as `data_schema`, and repair flows return `RepairsFlowResult`
- Use `probatio.Clamp()` for numeric inputs with min/max bounds (better UX than validation errors)
- Use `async_update_reload_and_abort()` for reconfigure flows
- Pass `step_id` to every `async_show_form`, `async_show_menu`, `async_show_progress` and
  `async_external_step` result (deprecation warning since HA 2026.10, required in 2027.5)
- Shared abort reasons (`already_in_progress`, `single_instance_allowed`, `reauth_successful`,
  `reconfigure_successful`, the OAuth ones) are translated by core since HA 2026.10 **only when**
  the abort passes `translation_domain=HOMEASSISTANT_DOMAIN`; drop the key from
  `translations/en.json` in that case and keep it otherwise
- Implement config entry migration (`async_migrate_entry()`) when changing config schema versions

## Entity and Device Patterns

### Device Registry

- Device identifier tuple: `(DOMAIN, unique_id)` where `unique_id` is MAC address, serial number, or similar
- `DeviceInfo` is a keyword-only dataclass since HA 2026.11: `DeviceInfo(identifiers=..., name=...)`,
  never a dict literal. Set manufacturer, model, sw_version and configuration_url
- Link a device to its hub with `via_device_id=<hub DeviceEntry.id>`; resolve the hub with
  `dr.async_get(hass).async_get_device_by_identifier((DOMAIN, hub_uid), entry.entry_id)`.
  Identifiers are unique per config entry only, so `async_get_device` (no entry id) and
  `via_device` (identifier tuple) are deprecated and removed in HA 2027.8
- Changing host/IP should not affect entity IDs or historical data

### Entity Unique IDs

- Sensor unique_id pattern: `{device_unique_id}_{sensor_key}`
- Use stable identifiers (MAC address, serial number) — not connection parameters (IP, hostname)
- Config entry type alias: `type MyConfigEntry = ConfigEntry[RuntimeData]`

### Entity Services

- Register entity services from the platform: `entity_platform.async_get_current_platform()
  .async_register_entity_service(name, schema, func)` (no `hass` argument). The module-level
  helper `homeassistant.helpers.service.async_register_platform_entity_service(hass, ...)` still
  takes `hass` as of 2026.11 and is for services registered outside a platform

### Follow-ups Tied to the HA Floor

- When the floor reaches HA 2026.12: `UNDEFINED` and `UndefinedType` are deprecated there in favour
  of `Undefined` (`homeassistant.helpers.typing`), removal in 2027.12. No change before that

### Repair Issues

- Create issues with `config_entry_id=entry.entry_id` (HA 2026.11): they are deleted with the
  entry and shown on its page. Use `config_subentry_id` for subentries from 2026.12
- Keep issues in step with reality inside `with ir.async_refresh_issues(hass, DOMAIN, issue_ids=...,
  config_entry_id=...)`: on exit it deletes every issue of the set not created or kept in the
  block, so no paired `async_delete_issue`, and an issue that stays keeps the user's ignore flag
- A fixable issue needs `async_create_fix_flow()` in `repairs.py`; its flow returns
  `RepairsFlowResult`

## Python Version & HA Baseline

These repos are standardized on the **Python 3.14+** toolchain:

- `pyproject.toml`: `requires-python = ">=3.14.2"` (matches Home Assistant
  core's own floor)
- `[tool.ruff]`: `target-version = "py314"`
- Minimum supported Home Assistant core: **2026.11.0** (per repo, in
  `.repo-sync.yaml`; `hacs.json` is rendered from the same value, so Marketplace users
  on older HA don't see updates). The scaffold starts at 2026.11.0, the release that
  brought `async_unload_platforms_or_raise`, `DeviceInfo` as a dataclass, issues bound
  to a config entry and the `async_entity_id_changed` hook; raise a consumer's floor
  when adopting those. Tests always run on the fleet-pinned `pytest-homeassistant`
  release, not on the floor.

**Implication for source code**: code in these repos may use 3.14-only
syntax (e.g. PEP 758's parenthesis-free `except A, B:`) and is **not**
backwards-compatible with Python 3.13. Ruff with `target-version = "py314"`
will actively *rewrite* `except (A, B):` into the parenthesis-free form —
which is a SyntaxError on Python 3.13. If a contributor's toolchain
regresses to 3.13, expect lint-fixes from these repos to fail to parse
locally until the toolchain is re-aligned.

## Dependencies Best Practices

### Dependency Update Checklist

**Before updating any dependency version in `manifest.json`:**

1. Verify the new version exists on PyPI: `https://pypi.org/project/PACKAGE_NAME/`
1. Check release notes for breaking changes
1. Test locally if possible

> **WARNING**: Always verify PyPI availability before committing dependency updates. Upstream maintainers
> sometimes create GitHub releases but forget to publish to PyPI, breaking the integration for users.

## Git Workflow

### Commit Messages

Use conventional commits with Claude attribution:

```text
feat(api): implement new feature

[Description]

Co-Authored-By: Claude <noreply@anthropic.com>
```

> **NEVER put a GitHub issue-closing keyword in a commit message.**
> `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`, `resolve`/`resolves`/`resolved`
> followed by `#N` auto-close that issue the moment the commit lands on the default
> branch. Reference issues with a neutral phrase only — "Refs #N", "Reported in #N",
> "Addresses #N". Issues are closed manually by the user, never by automation.

### Branch Strategy

- Default branch (`main` or `master`) = next release
- Create tags for releases
- Use pre-release flag for beta versions

## Pre-Commit Configuration

Linting tools and settings are defined in `.pre-commit-config.yaml`:

| Hook        | Tool                           | Purpose                      |
| ----------- | ------------------------------ | ---------------------------- |
| ruff        | `uvx ruff@X check --no-fix`    | Python linting               |
| ruff-format | `uvx ruff@X format --check`    | Python formatting            |
| jsonlint    | `uvx --from demjson3 jsonlint` | JSON validation              |
| yamllint    | `uvx yamllint@X -d "{...}"`    | YAML linting (inline config) |
| pymarkdown  | `uvx --from pymarkdownlnt==X pymarkdown scan` | Markdown linting |
| ty          | `uvx ty@X check --python "$(which python)"` | Type checking (needs the venv's HA) |

All hooks use `language: system` with `verbose: true` for visibility, and every tool
runs through `uvx` at the exact release CI uses (`[tool.repo-sync.tool-versions]` in the template
repo's `pyproject.toml`: ruff 0.16.8, ty 0.0.82,
yamllint 1.38.0, pymarkdownlnt 0.9.39).
Template changes reach this repo as signed `repo-sync/propagate` pull requests opened by the
template's `propagate.yml`; they auto-merge once the required checks pass. Do not edit those
files by hand: change the template and let it propagate.
ty and ruff are pre-1.0 / fast-moving and add rules between releases; unpinned they
turn CI red on code that passes locally. The dev extra and the dependency groups in
`pyproject.toml` are rendered into the shared block from the same pins (integration-specific
packages come from `dev_extra_requirements` in `.repo-sync.yaml`), so the venv copies of ruff
and ty that serve the VS Code extensions match CI too; dependabot ignores them.
`pytest-homeassistant` (the test package Home Assistant core publishes with every release) is
pinned fleet-wide to 2026.11.0; it pins `homeassistant` to that
same release, and ty reads the types Home Assistant ships (`py.typed`; `homeassistant-stubs` is
deprecated), so the type check and the tests see the same Home Assistant.

## Pre-Commit Checks (MANDATORY)

> **CRITICAL: ALWAYS run pre-commit checks before ANY git commit.**
> This is a hard rule - no exceptions. Never commit without passing all checks.

```bash
pre-commit run --all-files
```

> Use `pre-commit` directly, **not** `uvx pre-commit`. The `ty` hook
> resolves the interpreter at runtime via `$(which python)` to match the
> devcontainer venv. `uvx` would provision its own ephemeral Python 3.14
> first on PATH, and that env doesn't have Home Assistant installed —
> `ty` would false-fail with unresolved-import errors even though the
> code is fine. The git commit hook and CI's lint workflow already use
> the venv-installed `pre-commit`, so plain `pre-commit run` matches
> their behavior exactly.

Or run individual tools:

```bash
# Python formatting and linting
ruff format .
ruff check . --fix

# Markdown linting (same pinned release as the hook and CI)
uvx --from pymarkdownlnt==0.9.39 pymarkdown --config .pymarkdownlint.json scan .
```

All checks must pass before committing. This applies to ALL commits, not just releases.

### Windows Shell Notes

When running shell commands on Windows, stray `nul` files may be created (Windows null device artifact).
Check for and delete them after command execution:

```bash
rm nul  # if it exists
```

## Testing

Run the tests locally in the devcontainer before pushing. It installs the `dev` extra exactly as
the Tests workflow does (`uv pip install -e '.[dev]'`: same `pytest-homeassistant` pin, same Home
Assistant release), so a local pass is meaningful:

```bash
pytest tests/                                  # whole suite, no coverage (fast)
pytest tests/test_init.py -k setup             # one module or test
pytest tests/ --cov=custom_components/harmony_ng --cov-report=term-missing  # what CI runs
```

CI stays the gate: coverage (97% minimum) and the Release Readiness Report are read from the
Tests workflow run, never from a local run. Push, let the workflow run, then check it (see CI
Workflow Status and Logs).

> **CRITICAL: NEVER modify production code to make tests pass. Always fix the tests instead.**
> Production code is the source of truth. If tests fail, the tests are wrong - not the production code.
> The only exception is when production code has an actual bug that tests correctly identified.

## Quality Scale Tracking (MUST DO)

This integration tracks [Home Assistant Quality Scale][qs] rules in `quality_scale.yaml`.
Hassfest validates that file for core integrations only (its check returns early for custom
integrations), so here it is a tracking tool, not a CI gate. Once every rule of a tier is `done`
or `exempt`, declare the tier in `manifest.json` (`"quality_scale": "bronze"`, `silver`, `gold`
or `platinum`; the custom manifest schema accepts it) and keep the two in step. The scaffold
declares no tier because every rule starts as `todo`.

**When implementing new features or fixing bugs:**

1. Check if the change affects any quality scale rules
1. Update `quality_scale.yaml` status accordingly:
   - `done` - Rule is fully implemented
   - `todo` - Rule needs implementation
   - `exempt` with `comment` - Rule doesn't apply (explain why)
1. Aim to complete all Bronze tier rules first, then Silver, Gold, Platinum

[qs]: https://contributors.home-assistant.io/docs/core/integration-quality-scale/

## Release Management - CRITICAL

> **STOP: NEVER create git tags or GitHub releases without explicit user command.**
> This is a hard rule. Always stop after commit/push and wait for user instruction.

**Published releases are FROZEN** - Never modify the git tag, the ZIP asset, or the
`docs/releases/vX.Y.Z.md` file in a way that changes the meaning of what shipped.

The GitHub *release body* (what shows on the release page) may be edited via
`gh release edit vX.Y.Z --notes-file docs/releases/vX.Y.Z.md` to fix typos, add
cross-references to companion files that landed on `main` shortly after the release,
or clarify scope — as long as the edit doesn't misrepresent what's actually in the
released ZIP. When you do this, also update the matching `docs/releases/vX.Y.Z.md` so
the file and the live release body stay in sync.

**Master branch = Next Release** - All commits target the next version with version bumped
in manifest.json and const.py.

### Version Bumping Rules

> **IMPORTANT: Do NOT bump version during a session. All changes go into the CURRENT unreleased version.**

- The version in `manifest.json` and `const.py` represents the NEXT release being prepared
- **NEVER bump version until user commands "tag and release"**
- Multiple features/fixes can be added to the same unreleased version
- Only bump to a NEW version number AFTER the current version is released

### Version Locations (Must Be Synchronized)

1. `custom_components/harmony_ng/manifest.json` → `"version": "X.Y.Z"`
1. `custom_components/harmony_ng/const.py` → `VERSION = "X.Y.Z"`

> const.py must declare the version as plain `VERSION = "X.Y.Z"` — no `Final`
> annotation — because the release workflow and repo-sync validate that exact form.

### Complete Release Workflow

> **IMPORTANT: Version Validation**
> The release workflow VALIDATES that tag, manifest.json, and const.py versions all match.
> You MUST update versions BEFORE creating the release, not after.

| Step | Tool           | Action                                                                  |
| ---- | -------------- | ----------------------------------------------------------------------- |
| 1    | Edit           | Update `CHANGELOG.md` with version summary                              |
| 2    | Write          | Create `docs/releases/vX.Y.Z.md` release notes (see format below)      |
| 3    | Edit           | Ensure `manifest.json` and `const.py` have correct version              |
| 4    | Bash           | Run linting: `pre-commit run --all-files`                               |
| 5    | Bash           | `git add . && git commit -m "..."`                                      |
| 6    | Bash           | `git push`                                                              |
| 7    | **STOP**       | Wait for user "tag and release" command                                 |
| 8    | **CI Check**   | Verify ALL CI workflows pass (see CI Verification below)                |
| 9    | **RRR**        | Display Release Readiness Report (see below)                            |
| 10   | Bash           | `git tag -a vX.Y.Z -m "Release vX.Y.Z"`                                |
| 11   | Bash           | `git push --tags`                                                       |
| 12   | gh CLI         | `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file docs/releases/vX.Y.Z.md` |
| 13   | GitHub Actions | Validates versions match, then auto-uploads ZIP asset                   |
| 14   | Edit           | Bump versions in `manifest.json` and `const.py` to next version         |

### CI Verification (MANDATORY)

> **CRITICAL: Before tagging/releasing, ALWAYS verify ALL CI workflows are passing.**
> Use GitHub MCP tools to list workflow runs, then use `gh` CLI to get detailed logs if needed.
> NEVER proceed if any workflow is failing.

**Verification steps:**

1. Use `mcp__GitHub_MCP_Remote__actions_list` to list recent workflow runs:

   ```text
   actions_list(method="list_workflow_runs", owner="alexdelprete", repo="ha-harmony-ng")
   ```

1. Check that ALL workflows show `conclusion: "success"`:
   - Lint workflow
   - Validate workflow
   - Tests workflow

1. If any workflow is failing, use `gh` CLI to get detailed failure logs:

   ```bash
   # View failed run logs (replace <run_id> with actual ID from step 1)
   gh run view <run_id> --log-failed

   # Or view full logs for a specific run
   gh run view <run_id> --log
   ```

1. Fix failing tests/issues, commit, push, and re-verify before proceeding

### Release Notes Format (MANDATORY)

Create a release notes file at `docs/releases/vX.Y.Z.md` using this template.
This file is then used as the body when creating the GitHub release.

```markdown
# Release vX.Y.Z

[![GitHub Downloads](https://img.shields.io/github/downloads/alexdelprete/ha-harmony-ng/vX.Y.Z/total?style=for-the-badge)](https://github.com/alexdelprete/ha-harmony-ng/releases/tag/vX.Y.Z)

**Release Date:** YYYY-MM-DD

**Type:** [Major/Minor/Patch/Beta] release - Brief description.

## What's Changed

### Added

- Feature 1

### Changed

- Change 1

### Fixed

- Fix 1

**Full Changelog**:
[compare/vPREV...vX.Y.Z](https://github.com/alexdelprete/ha-harmony-ng/compare/vPREV...vX.Y.Z)
```

### Release Readiness Report (MANDATORY)

> **When user commands "tag and release", ALWAYS display the Release Readiness Report (RRR) BEFORE proceeding.**

Check CI workflows and display:

```markdown
## Release Readiness Report (RRR)

| Check | Status | Details |
|-------|--------|---------|
| **Lint** | status | date |
| **Tests** | status | date |
| **Validate** | status | date |
| **Test Coverage** | status | Minimum required: 97% |
| **Version** | X.Y.Z | manifest.json + const.py |
| **CHANGELOG.md** | status | Updated |
| **Release notes** | status | docs/releases/vX.Y.Z.md |
| **Working Tree** | status | No uncommitted changes |
```

**Test Coverage Requirement:**

> **CRITICAL: Test coverage MUST be at minimum 97%.**
> If coverage drops below 97%, flag it and do not proceed with release until fixed.

**How to get test coverage:**

```bash
gh run list --repo alexdelprete/ha-harmony-ng --limit 5 | grep Tests
gh run view <run_id> --repo alexdelprete/ha-harmony-ng --log 2>&1 | grep "TOTAL"
```

The coverage percentage is the last column in the TOTAL line.

### Issue References in Release Notes

When a release addresses a specific GitHub issue:

- Reference the issue number, but **NEVER use a GitHub closing keyword** —
  `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`, `resolve`/`resolves`/`resolved`
  followed by `#N` — anywhere in commit messages, release notes, the GitHub release
  body, or PR descriptions. Those keywords auto-close the issue when the commit lands
  on the default branch. Use a neutral phrase instead: "Reported in #42",
  "Addresses #42", "Refs #42".
- Thank the user who opened the issue by name and GitHub handle.
- **NEVER close the issue** — the user will do it manually.

### After Publishing a Release

1. Immediately bump versions in `manifest.json` and `const.py` to next version
1. Create new release notes file for next version
1. Mark previous version's documentation as frozen

### Release Documentation Structure

#### Stable/Official Release Notes (e.g., v1.0.0)

- **Scope**: ALL changes since previous stable release
- **Example**: v1.1.0 includes everything since v1.0.0
- **Purpose**: Complete picture for users upgrading from last stable

#### Beta Release Notes (e.g., v1.0.0-beta.1)

- **Scope**: Only incremental changes in this beta
- **Example**: v1.0.0-beta.2 shows only what's new since beta.1
- **Purpose**: Help beta testers focus on what to test

### Documentation Files

- **`CHANGELOG.md`** (root) — quick overview of all releases, Keep a Changelog format
- **`docs/releases/`** — detailed release notes (one file per version)
- **`docs/releases/README.md`** — release directory guide and templates

## Do's and Don'ts

**DO:**

- Run `pre-commit run --all-files` before EVERY commit (NOT `uvx pre-commit` — see Pre-Commit Checks section for why)
- Run `pytest tests/` in the devcontainer before pushing; CI remains the gate for coverage
- Read CLAUDE.md at session start
- Use `runtime_data` for data storage (not `hass.data[DOMAIN]`)
- Use `@callback` decorator for message handlers
- Log with `%s` formatting (not f-strings)
- Handle missing data gracefully
- Update both manifest.json AND const.py for version bumps
- Get approval before creating tags/releases
- Use custom exceptions for error handling
- Verify PyPI availability before updating dependencies

**NEVER:**

- Commit without running pre-commit checks first
- Modify production code to make tests pass - fix the tests instead
- Use `hass.data[DOMAIN][entry_id]` - use `runtime_data` instead
- Shadow Python builtins (A001)
- Use f-strings in logging (G004)
- Create git tags or GitHub releases without explicit user instruction
- Forget to update VERSION in both manifest.json AND const.py
- Use blocking calls in async context
- Close GitHub issues without explicit user instruction
- Log manually what HA logs automatically (coordinator errors, ConfigEntryNotReady)
- Create documentation files without user request

<!--
==============================================================================
⚠️  END OF TEMPLATE-MANAGED ZONE.

The END SHARED marker line appears below this comment. Anything you add
BELOW the END SHARED marker is integration-specific and safe to edit —
it will not be touched by `repo-sync.py`.
==============================================================================
-->

<!-- END SHARED:repo-sync -->

## Reference Documentation

- [Home Assistant Contributor Docs](https://contributors.home-assistant.io/)
