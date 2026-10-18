# ESPHome OTA for Home Assistant

<!-- hass-standards:badges:start -->
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](#installation)
[![Release](https://img.shields.io/github/v/release/eigger/hass-esphome-ota?style=flat-square)](https://github.com/eigger/hass-esphome-ota/releases)
[![Home Assistant minimum](https://img.shields.io/badge/HA-%E2%89%A5%202024.1.0-41BDF5?style=flat-square)](hacs.json)
[![Tests](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/tests.yml?branch=main&style=flat-square&label=Tests)](https://github.com/eigger/hass-esphome-ota/actions/workflows/tests.yml)
[![Validate](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/validate.yml?branch=main&style=flat-square&label=Validate)](https://github.com/eigger/hass-esphome-ota/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/eigger/hass-esphome-ota?style=flat-square)](LICENSE)
[![Analytics reporting installs](https://img.shields.io/badge/dynamic/json?style=flat-square&color=41BDF5&label=Usage&query=%24.esphome_ota.total&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json)](https://analytics.home-assistant.io/)
<!-- hass-standards:badges:end -->

**English** | [한국어](README.ko.md)

**ESPHome OTA** is a Home Assistant custom integration (HACS) for building and publishing ESPHome firmware over HTTP OTA. It connects to the **ESPHome Device Builder** add-on's trusted loopback listener inside Home Assistant OS, so no public ports, `leave_front_door_open`, or login tokens are needed. It is a HACS custom integration, not an official Home Assistant Core integration.

## Supported features

- Automatic, zero-config discovery of the ESPHome Builder add-on and a live device list.
- Safe, diff-based YAML preparation (`packages.esphome_ota`) that preserves `!secret`, `!include`, and comments.
- Compile, verify, and publish pipeline with live logs, binary integrity checks, and atomic publishing to `/local/esphome_ota/`.
- Sidebar panel with batch builds, job cancellation, and first-install guidance; manual firmware upload; import from the legacy add-on.

More detail and the architecture overview: [docs/features.md](docs/features.md).

## Requirements

- Home Assistant with the ESPHome Device Builder add-on (Home Assistant OS / Supervised).
- `hacs.json` declares Home Assistant 2024.1.0 as the minimum, but the code currently needs a newer release (see [docs/development.md](docs/development.md#verified-environments)). CI verifies Home Assistant 2026.10.2.
- A Base URL that your ESPHome devices can reach.

## Installation

1. In HACS open **Custom repositories**, add `https://github.com/eigger/hass-esphome-ota` as category **Integration**.
2. Download **ESPHome OTA** and restart Home Assistant.
3. Go to **Settings** > **Devices & Services** > **Add Integration** and select **ESPHome OTA**.

Manual installation: copy `custom_components/esphome_ota` into `<config>/custom_components/` and restart. To remove, delete the integration entry, then that folder (and, if no longer needed, the published firmware in `www/esphome_ota/` and the private archive `/config/esphome_ota/firmware/`; neither is removed automatically).

## Quick start

1. After adding the integration the Builder is discovered automatically; confirm and save the Base URL. Then open **ESPHome OTA** in the sidebar; devices known to the Builder are listed.
2. Click **Prepare OTA** on a device, review the YAML diff, and click **Apply to YAML**.
3. Click **Build & Publish** and watch the live log; the manifest and binary are published to `/local/esphome_ota/`.
4. Devices without HTTP OTA need a one-time USB or local OTA flash; later updates can be installed remotely through the Home Assistant Update entity over HTTP OTA.

## Important limitations

- Publishing firmware is not the same as installing it on a device; the panel reports them separately.
- Discovering a device never edits YAML or starts a build on its own.
- Verified with automated tests against a real Home Assistant; behavior with physical devices and a live Builder is covered only by the manual procedure in [docs/validation.ko.md](docs/validation.ko.md) (Korean).

## Legacy migration

Coming from the ESPHome OTA Publisher add-on? Use **Import from Legacy Add-on** at the top right of the panel and review the preview of devices and binaries. It reads `esphome/ota_server/registered.json`, copies binaries from `www/esphome_ota/` into private storage, and keeps tokens and device slugs. Stop or uninstall the add-on afterwards.

## Documentation

- [Features and architecture](docs/features.md)
- [Development and testing](docs/development.md)
- [Design notes (Korean)](docs/architecture.ko.md)
- [Live validation on HA OS (Korean)](docs/validation.ko.md)

## Support

Report bugs and request features through [GitHub Issues](https://github.com/eigger/hass-esphome-ota/issues). GitHub Discussions is not enabled for this repository.

## License

Released under the [MIT License](LICENSE).
