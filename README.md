# Harmony NG

<!-- BEGIN SHARED:repo-sync:badges -->
<!-- Synced by repo-sync on 2026-11-06 -->

[![GitHub Release](https://img.shields.io/github/v/release/alexdelprete/ha-harmony-ng?style=for-the-badge)](https://github.com/alexdelprete/ha-harmony-ng/releases)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/alexdelprete)
[![Tests](https://img.shields.io/github/actions/workflow/status/alexdelprete/ha-harmony-ng/test.yml?style=for-the-badge&label=Tests)](https://github.com/alexdelprete/ha-harmony-ng/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/codecov/c/github/alexdelprete/ha-harmony-ng?style=for-the-badge)](https://codecov.io/gh/alexdelprete/ha-harmony-ng)
[![GitHub Downloads](https://img.shields.io/github/downloads/alexdelprete/ha-harmony-ng/total?style=for-the-badge)](https://github.com/alexdelprete/ha-harmony-ng/releases)

<!-- END SHARED:repo-sync:badges -->

Home Assistant integration for a Logitech Harmony Hub running the open-source
[harmony-ng](https://github.com/iranl/harmony-ng) firmware. The Hub pushes every change over a
WebSocket, so activities, remotes and Bluetooth hosts update in Home Assistant the moment they
change, without polling. The integration replaces the core Harmony integration for these Hubs, which
no longer speak the Logitech protocol.

## Supported devices

- Logitech Harmony Hub (the base of the Elite, Ultimate, Companion and Smart Control bundles)
  running harmony-ng with the event bus (`api_version` 2 or newer). Older harmony-ng releases and
  stock Logitech firmware are not supported.
- RF remotes paired with the Hub: Harmony Elite, Ultimate, Companion and Smart Control. Each remote
  is a device of its own, identified by its unit id when the remote's firmware reports it.
- Bluetooth hosts paired with the Hub appear as connectivity sensors.

## Features

- One `remote` entity per Hub with the attributes and services of the core Harmony integration, so
  existing automations port with a change of entity id: `remote.turn_on` with an activity,
  `remote.turn_off`, `remote.send_command` with device, repeats, delay and hold.
- Activity select and one button per activity, activity state, firmware and last-boot sensors,
  a busy indicator.
- Each configured device is a child device of the Hub with its own `remote` entity and one button
  per command it knows. The command buttons are disabled by default; enable the ones you use.
- Per remote: battery, voltage, charging and configuration-sync sensors, wake and sleep buttons,
  and an `event` entity for every key press and release.
- Infrared emitters for the front blaster and the two emitter jacks, usable by Home Assistant's
  infrared integrations (LG, Samsung, Marantz, Dyson and others) as their transmitter.
- Services for device commands on chosen outputs, Bluetooth keys, Help and cancel.
- Discovery through mDNS; manual setup by address also works. Optional Personal Access
  Token when the Hub has authentication enabled.

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

The Hub is found automatically on the local network. Otherwise add the integration from
**Settings > Devices & services** and enter the Hub's address.

<!-- pyml disable md013 -->

| Parameter | Where | Meaning |
| --- | --- | --- |
| Host, port | setup and reconfigure | The Hub's address and API port, 8089 by default |
| Transport | setup and reconfigure | API, the default: direct to the Hub. MQTT: through your broker and the Home Assistant MQTT integration. Both give the same entities, and switching keeps them |
| MQTT base topic | setup and reconfigure, MQTT only | The base topic configured on the Hub, `harmony/hub` by default |
| Personal Access Token | setup, reauthenticate, reconfigure | Only when the Hub has authentication enabled; create one in the Hub's web UI under Users |
| Default activity | options | Activity started by `remote.turn_on` without an activity: the previous one or a named one |
| Delay between commands | options | Seconds between the commands of one `remote.send_command` call, 0.4 by default |

<!-- pyml enable md013 -->

Changing the Hub's address keeps every entity: the Hub is identified by its unit id, never by
its address.

## Actions

Besides the standard `remote` actions, the integration provides:

<!-- pyml disable md013 -->

| Action | What it does |
| --- | --- |
| `harmony_ng.ir_send` | Sends a device command by name on the chosen infrared outputs |
| `harmony_ng.bt_key` | Sends a keyboard key to a paired Bluetooth host |
| `harmony_ng.activity_help` | Re-sends the running activity's start commands and returns the devices whose power is a toggle |
| `harmony_ng.activity_help_answer` | Answers the Help question for one device |
| `harmony_ng.activity_cancel` | Clears a stuck activity change |
| `harmony_ng.sync` | Pushes the Hub's configuration to the remotes |

<!-- pyml enable md013 -->

All actions target the Hub device; the entity action `harmony_ng.sync` targets the remote entity.

### Triggers and conditions

Every remote has an `event` entity that fires on each key press and release with the key name,
the mapped device and command as attributes; use it with the **event** trigger. Activity changes
are available as state triggers on the `select` and `sensor` entities and as conditions on the
`remote` entity's state and `current_activity` attribute.

### Examples

```yaml
# Start an activity by name
action: remote.turn_on
target:
  entity_id: remote.living_room_hub
data:
  activity: Watch TV

# Hold volume up on the TV for a second
action: remote.send_command
target:
  entity_id: remote.living_room_hub
data:
  device: LG OLED TV
  command: VolumeUp
  hold_secs: 1

# Act on a key of the physical remote
triggers:
  - trigger: event
    entity_id: event.harmony_ultimate_button
    event_type: press
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.button == 'Menu' }}"
```

## Data updates

The Hub pushes events over its WebSocket, or over MQTT on that transport; nothing is polled.
Inventory and activities are read once at startup and again when the Hub reports a configuration
change. If the connection drops, every entity becomes unavailable until the integration reconnects,
which it does with increasing delays up to 30 seconds.

## Known limitations

- The Hub needs harmony-ng firmware with the event bus. The integration refuses older firmware
  and raises a repair issue saying so.
- A remote running older firmware does not report its unit id; it is then identified by its
  slot until the id arrives, and re-keyed automatically when it does.
- Infrared emitters send raw timings only; Pronto codes go through the Hub's own device
  commands, not through the emitter entities.
- The MQTT transport needs MQTT enabled on the Hub, firmware with the MQTT rewrite, and the
  Home Assistant MQTT integration. Over MQTT, the firmware update check and Help need firmware
  whose command channel has those actions; on older firmware the update entity stays unknown.
- A remote's product name (Harmony Ultimate, Elite, 950 and so on) needs firmware that reports
  it. Until then a touchscreen remote is shown as "Harmony remote" without a model.

## Troubleshooting

- **Cannot connect** during setup: check that the Hub answers at `http://<host>:8089` in a browser
  and that no firewall sits between Home Assistant and the Hub.
- **Entities unavailable**: the connection to the Hub dropped (the WebSocket, or the broker on
  the MQTT transport). The integration reconnects by
  itself; a Hub restart takes about a minute. Diagnostics (three-dot menu of the entry) show the
  last state and the transport's connection flag.
- **Repair issue about the Logitech protocol**: the Hub has the legacy protocol enabled, so the
  core Harmony integration can also see it and would create duplicate entities. Disable the
  setting on the Hub or remove the core integration's entry for this Hub.
- **Commands refused as busy**: the Hub is switching activities; wait for it to finish or use
  `harmony_ng.activity_cancel` if it is stuck. Firmware with the activity request queue does not
  refuse an activity start or power off during a switch: it runs the latest one when the switch
  completes.

## Removal

Delete the entry from **Settings > Devices & services**. Nothing is left on the Hub; a Personal
Access Token created for Home Assistant can be revoked in the Hub's web UI.

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
