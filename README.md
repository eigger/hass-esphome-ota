<!-- hass-standards:header:start -->
# ESPHome OTA for Home Assistant

**ESPHome OTA** is a Home Assistant custom integration (HACS) for building and publishing ESPHome firmware over HTTP OTA. It connects to the **ESPHome Device Builder** add-on's trusted loopback listener inside Home Assistant OS, so no public ports, `leave_front_door_open`, or login tokens are needed. It is a HACS custom integration, not an official Home Assistant Core integration.

**English** | [한국어](README.ko.md)

<!-- hass-standards:badges:start -->
[![Release](https://img.shields.io/github/v/release/eigger/hass-esphome-ota?style=flat)](https://github.com/eigger/hass-esphome-ota/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat)](#installation)
[![Home Assistant minimum](https://img.shields.io/badge/HA-%E2%89%A5%202024.11.0-41BDF5?style=flat)](hacs.json)
[![Tests](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/tests.yml?branch=main&style=flat&label=Tests)](https://github.com/eigger/hass-esphome-ota/actions/workflows/tests.yml)
[![Validate](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/validate.yml?branch=main&style=flat&label=Validate)](https://github.com/eigger/hass-esphome-ota/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/eigger/hass-esphome-ota?style=flat)](LICENSE)
[![Downloads](https://img.shields.io/github/downloads/eigger/hass-esphome-ota/latest/total?style=flat&color=41BDF5&label=Downloads)](https://github.com/eigger/hass-esphome-ota/releases)
<!-- hass-standards:badges:end -->
<!-- hass-standards:header:end -->

![ESPHome OTA](custom_components/esphome_ota/brand/logo.png)

## Supported features

- Automatic, zero-config discovery of the ESPHome Builder add-on and a live device list.
- Safe, diff-based YAML preparation (`packages.esphome_ota`) that preserves `!secret`, `!include`, and comments.
- Compile, verify, and publish pipeline with live logs, binary integrity checks, and atomic publishing to `/local/esphome_ota/`.
- Supported targets: ESP32 family and ESP8266. RP2040/RP2350 devices are not supported (their firmware has no verifiable header) and are rejected before a build starts.
- Sidebar panel with batch builds, job cancellation, and first-install guidance; manual firmware upload.

More detail and the architecture overview: [docs/features.md](docs/features.md).

## Requirements

- Home Assistant with the ESPHome Device Builder add-on (Home Assistant OS / Supervised).
- Home Assistant 2024.11.0 or newer is required (`hacs.json`; see [docs/development.md](docs/development.md#verified-environments)). CI verifies Home Assistant 2026.10.4.
- A Base URL that your ESPHome devices can reach.

## Installation

<!-- hass-standards:installation:start -->
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eigger&repository=hass-esphome-ota&category=integration)
<!-- hass-standards:installation:end -->

1. In HACS search for **ESPHome OTA** and download it (or use the button above).
2. Restart Home Assistant.
3. Go to **Settings** > **Devices & Services** > **Add Integration** and select **ESPHome OTA**.

Before it appears in the default HACS catalog you can add `https://github.com/eigger/hass-esphome-ota` under **Custom repositories** (category **Integration**) instead.

Manual installation: copy `custom_components/esphome_ota` into `<config>/custom_components/` and restart. To remove, delete the integration entry, then that folder (and, if no longer needed, the published firmware in `www/esphome_ota/` and the private archive `/config/esphome_ota/firmware/`; neither is removed automatically).

## Quick start

1. After adding the integration the Builder is discovered automatically; confirm and save the Base URL. Then open **ESPHome OTA** in the sidebar; devices known to the Builder are listed.
2. Click **Prepare OTA** on a device, review the YAML diff, and click **Apply to YAML**.
3. Click **Build & Publish** and watch the live log; the manifest and binary are published to `/local/esphome_ota/`.
4. Devices without HTTP OTA need a one-time USB or local OTA flash; later updates can be installed remotely through the Home Assistant Update entity over HTTP OTA.

## Important limitations

- Publishing firmware is not the same as installing it on a device; the panel reports them separately.
- Published firmware is served from `/local/` without authentication and contains the device's Wi-Fi, API and OTA secrets. Its URL is protected only by a random token of at least 32 hex characters, which every device is required to have; keep it private.
- Discovering a device never edits YAML or starts a build on its own.
- Verified with automated tests against a real Home Assistant; behavior with physical devices and a live Builder is covered only by the manual procedure in [docs/validation.ko.md](docs/validation.ko.md) (Korean).

## Coming from the legacy add-on

The import from the ESPHome OTA Publisher add-on has been removed. Stop or uninstall the add-on and delete its leftover files in `www/esphome_ota/` (uninstalling does not remove them; they are served without authentication and contain device secrets). Then set devices up again here: **Prepare OTA**, **Build & Publish**, and one install through ESPHome Builder. Devices imported by an earlier release keep working; any of them without a strong token gets a new one at startup and needs that one install as well. At startup the integration logs a warning for any public firmware left at a guessable URL.

## Documentation

- [Features and architecture](docs/features.md)
- [Development and testing](docs/development.md)
- [Design notes (Korean)](docs/architecture.ko.md)
- [Live validation on HA OS (Korean)](docs/validation.ko.md)

### Repository support

Report bugs and request features through [GitHub Issues](https://github.com/eigger/hass-esphome-ota/issues). GitHub Discussions is not enabled for this repository.

<!-- hass-standards:support:start -->
## Support

- [Issues](https://github.com/eigger/hass-esphome-ota/issues): Report bugs or request features.
<!-- hass-standards:support:end -->

<!-- hass-standards:related-projects:start -->
<!-- hass-standards:related-projects:end -->

<!-- hass-standards:license:start -->
## License

Released under the [MIT License](LICENSE).
<!-- hass-standards:license:end -->
