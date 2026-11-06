# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Integration skeleton moved to the Home Assistant 2026.11 APIs: probatio
  schemas, setup and unload that raise on failure, a base entity with keyword
  `DeviceInfo` and in-place entity ID renames, and a device-offline repair issue
  linked to the integration entry.
- Minimum supported Home Assistant version raised to 2026.11.0.
- Manifest declares the Marketplace category `buttons_remotes`.
- Tests run on `pytest-homeassistant` 2026.11.0, the test package published by
  Home Assistant core.
