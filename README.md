<!-- hass-standards:header:start -->
# ESPHome OTA for Home Assistant

A Home Assistant custom integration that connects to the ESPHome Device Builder add-on, builds your ESPHome firmware there and serves it to your devices over HTTP OTA. The add-on needs no extra configuration.

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

## Requirements

- **Home Assistant:** 2024.11.0 or later.
- **Add-on:** The ESPHome Device Builder add-on, installed and running, on Home Assistant OS or Supervised. The integration finds it through the Supervisor; Container and Core installs and an external Builder are not supported.
- **Base URL:** The external address of Home Assistant that your ESPHome devices use to download firmware. For OTA from outside your network it must be reachable from the internet (domain and HTTPS).

## Installation

<!-- hass-standards:installation:start -->
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eigger&repository=hass-esphome-ota&category=integration)
<!-- hass-standards:installation:end -->

1. Click the badge above to open the repository in Marketplace.
2. If you need to add it yourself, go to **Settings → Marketplace → Add from link** and enter <https://github.com/eigger/hass-esphome-ota>. Connect GitHub if prompted.
3. Select **Install**. Restart Home Assistant if prompted, then continue to [Configuration](#configuration).

## Configuration

Open **Settings → Devices & services → Add integration → ESPHome OTA**.

1. If more than one ESPHome Builder is found, choose the one to use. With a single Builder it is selected automatically.
2. Enter the **Public Base URL**: the external address of Home Assistant that your devices use to fetch firmware (for example `https://ha.example.com`).

Afterwards, **Configure** on the integration entry changes the Base URL, the Builder, and the **Default auto-hide period (hours)** (0 = never hide automatically). See [Important limitations](#important-limitations) before publishing.

### Uninstall

Before removing the integration, click **Remove OTA** on each device card in the panel if you want the `packages.esphome_ota` block removed from its YAML; removing the integration entry does not edit your YAML. Then remove the integration entry and uninstall it from Marketplace. Published firmware in `www/esphome_ota/` and the private archive in `/config/esphome_ota/firmware/` are retained. Delete them only if they are no longer needed.

## Quick start

1. After adding the integration the Builder is discovered automatically; confirm and save the Base URL. Then open **ESPHome OTA** in the sidebar; devices known to the Builder are listed.
2. Click **Prepare OTA** on a device, review the YAML diff, and click **Apply to YAML**.
3. Click **Build & Publish** and watch the live log; the manifest and binary are published to `/local/esphome_ota/`.
4. Devices without HTTP OTA need a one-time USB or local OTA flash; later updates can be installed remotely through the Home Assistant Update entity over HTTP OTA.

## Important limitations

- Publishing firmware is not the same as installing it on a device; the panel reports them separately.
> [!WARNING]
> **Published firmware contains your device secrets and is served without authentication.**
>
> - This integration only makes Home Assistant serve your OTA firmware; it does not decide who may reach it. Whether, how widely and for how long that file is reachable from the internet (public OTA) is your responsibility, so expose it only as much as you need.
> - ESPHome resolves `!secret` values at compile time, so the built `.ota.bin` embeds your Wi-Fi SSID and password, API encryption key and OTA password in plain text. Anyone who downloads the file can read them.
> - The file is served from `/local/esphome_ota/` with no Home Assistant login. Its only protection is a random token of at least 32 hex characters in the URL, which every device is required to have. Treat the URL like a password: do not share it or paste it in issues, screenshots or logs.
> - Keep the exposure window short. Firmware is hidden automatically once the installation is verified (default on) and after the **Auto-hide after (hours)** time (default 12 hours); hide it manually if you do not need it published.
> - Hiding removes the public file but does not cancel a download already in progress or a copy cached by a reverse proxy or CDN. If you suspect the URL leaked, rotate the Wi-Fi password, API key and OTA password.

- Discovering a device never edits YAML or starts a build on its own.
- Verified with automated tests against a real Home Assistant; behavior with physical devices and a live Builder is not covered by automated tests.

## Troubleshooting

If the integration cannot reach the Builder, or a build or install fails, see [Connection diagnostics and troubleshooting](docs/troubleshooting.md).

<!-- hass-standards:support:start -->
## Support

- [Issues](https://github.com/eigger/hass-esphome-ota/issues): Report bugs or request features.
- [Discussions](https://github.com/eigger/hass-esphome-ota/discussions): Ask questions and share your experience.
<!-- hass-standards:support:end -->

<!-- hass-standards:related-projects:start -->
<!-- hass-standards:related-projects:end -->

<!-- hass-standards:license:start -->
## License

Released under the [MIT License](LICENSE).
<!-- hass-standards:license:end -->
