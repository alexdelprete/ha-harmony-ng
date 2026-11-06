# Harmony NG

<!-- BEGIN SHARED:repo-sync:badges -->
<!-- Synced by repo-sync on 2026-11-06 -->

[![GitHub Release](https://img.shields.io/github/v/release/alexdelprete/ha-harmony-ng?style=for-the-badge)](https://github.com/alexdelprete/ha-harmony-ng/releases)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/alexdelprete)
[![Tests](https://img.shields.io/github/actions/workflow/status/alexdelprete/ha-harmony-ng/test.yml?style=for-the-badge&label=Tests)](https://github.com/alexdelprete/ha-harmony-ng/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/codecov/c/github/alexdelprete/ha-harmony-ng?style=for-the-badge)](https://codecov.io/gh/alexdelprete/ha-harmony-ng)
[![GitHub Downloads](https://img.shields.io/github/downloads/alexdelprete/ha-harmony-ng/total?style=for-the-badge)](https://github.com/alexdelprete/ha-harmony-ng/releases)

<!-- END SHARED:repo-sync:badges -->

A Home Assistant custom integration for Harmony NG.

## Features

- TODO: List features

<!-- BEGIN SHARED:repo-sync:installation -->
<!-- Synced by repo-sync on 2026-11-06 -->

## Installation

### Marketplace (Recommended)

Home Assistant 2026.11 and later ship the Marketplace, which replaces HACS. If this
integration is not listed in the catalog, add the repository by link:

1. Open **Settings** → **Marketplace** in your Home Assistant instance (administrators only;
   custom repositories require a GitHub connection)
1. Select **Add from link** in the upper-right corner
1. Enter `https://github.com/alexdelprete/ha-harmony-ng` and select **Add**
1. Open the repository page, select **Install**, review the version and confirm
1. Restart Home Assistant when a repair asks you to, then add the integration under
   **Settings** → **Devices & services**

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/alexdelprete/ha-harmony-ng/releases)
1. Extract the `custom_components/harmony_ng` folder
1. Copy it to your Home Assistant `config/custom_components/` directory
1. Restart Home Assistant

<!-- END SHARED:repo-sync:installation -->

## Configuration

TODO: Describe configuration steps.

<!-- BEGIN SHARED:repo-sync:contributing -->
<!-- Synced by repo-sync on 2026-11-06 -->

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
1. Create a feature branch (`git checkout -b feature/my-feature`)
1. Make your changes
1. Run linting: `pre-commit run --all-files`
1. Commit your changes (`git commit -m "feat: add my feature"`)
1. Push to your branch (`git push origin feature/my-feature`)
1. Open a Pull Request

Please ensure all CI checks pass before requesting a review.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development environment (devcontainer, tests, live
Home Assistant instance) and the Windows caveats.

<!-- END SHARED:repo-sync:contributing -->

<!-- BEGIN SHARED:repo-sync:license -->
<!-- Synced by repo-sync on 2026-11-06 -->

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

<!-- END SHARED:repo-sync:license -->
