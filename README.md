# ESPHome OTA for Home Assistant

[![HACS Custom Integration](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-54%20Passed-brightgreen.svg)]()

[한국어 문서 (README.ko.md)](README.ko.md)

**ESPHome OTA** is a Home Assistant custom component designed to streamline remote HTTP firmware builds and publication for ESPHome devices. It automatically connects to the **ESPHome Device Builder** add-on trusted loopback listener within Home Assistant OS—eliminating the need for open public ports, `leave_front_door_open`, or manual login tokens.

---

## Key Features

- **Automatic Zero-Config Builder Discovery**: Discovers running ESPHome Builder add-ons and services on HA loopback without requiring manual URL, port, or dashboard tokens.
- **Direct Device Inventory Synchronization**: Displays devices known to ESPHome Builder in real time without scanning local directories or manual registration forms.
- **Safe YAML Configuration Diff**: Injects managed `packages.esphome_ota` configuration via Compare-And-Swap (CAS), preserving existing custom code, `!secret`, `!include`, and comments.
- **Robust Compile & Publish Pipeline**:
  - Triggers compilation via Builder API and streams output live.
  - Explicit completion validation (rejects `unknown` or silent stream closures).
  - Single-use token downloads directly to private artifact storage.
  - Binary integrity inspection: chip family validation (`esp_image_header_t`), GCC build times, framework and project boot versions.
  - Atomic publishing with cache-busting headers (`?v=<md5>`) to `/local/esphome_ota/`.
- **First-Time Install Guidance**: Clearly distinguishes between firmware publication and actual device installation, guiding users when an initial USB or local OTA flash is required.
- **Native Custom Sidebar Panel**:
  - Responsive, modern dashboard adhering to Home Assistant theme variables and dark mode.
  - Real-time WebSocket subscription for instant status, device, and job progress updates.
  - Live log streaming terminal and job cancellation.
  - Multi-device batch building and publishing.
- **Legacy Add-on Data Migration**: Seamlessly imports `registered.json`, device wrappers, tokens, and existing binaries from the legacy ESPHome OTA Publisher add-on.
- **Multipart Manual Upload View**: Secure authenticated HTTP endpoint for manual firmware uploads up to 16 MiB.
- **Privacy-Preserving Diagnostics**: Redacts secret tokens, URLs, and confidential YAML from diagnostic dumps.

---

## Architecture Overview

```text
[ HA Sidebar Panel ]
       │  HA Admin WebSocket API
       ▼
 [ OtaManager ] ──► [ BuilderResolver ] ──► Loopback WS/HTTP (127.0.0.1:<port>)
       │                                     └─► ESPHome Device Builder
       ├──────────► [ DeviceManager ]
       ├──────────► [ JobRunner ]
       │                 └─► Compile -> Checkpoint -> Download -> Verify
       ├──────────► [ ArtifactPublisher ]
       │                 ├─► Private Archive: /config/esphome_ota/firmware/
       │                 └─► Public Release:  /config/www/esphome_ota/
       └──────────► [ InstallationMonitor ] ◄── HA Update Entities
```

---

## Installation

### Method 1: Via HACS (Recommended)
1. Open HACS in your Home Assistant sidebar.
2. Select **Integrations** > **Custom repositories** (three dots in top right).
3. Add this repository URL (`https://github.com/eigger/hass-esphome-ota`) with category **Integration**.
4. Search for **ESPHome OTA** and click **Download**.
5. Restart Home Assistant.

### Method 2: Manual Installation
1. Clone or download this repository.
2. Copy `custom_components/esphome_ota` to your Home Assistant `<config>/custom_components/` directory:
   ```bash
   cp -r custom_components/esphome_ota /config/custom_components/
   ```
3. Restart Home Assistant.

---

## Quick Start & Workflow

1. **Add Integration**:
   - Go to **Settings** > **Devices & Services** > **Add Integration**.
   - Search for **ESPHome OTA**.
   - The integration will automatically discover your ESPHome Builder add-on. Confirm your public Home Assistant Base URL.
2. **Access Panel**:
   - Open **ESPHome OTA** from the sidebar.
   - Devices managed by ESPHome Builder are listed automatically.
3. **Prepare Device**:
   - Click **Prepare OTA** on a device card.
   - Review the proposed YAML diff and click **Apply to YAML**.
4. **Build & Publish**:
   - Click **Build & Publish**.
   - View live compilation progress in the terminal dialog.
   - Once published, your device's manifest and binary are deployed to `/local/esphome_ota/`.
5. **Initial Install (If Needed)**:
   - For devices that do not yet have HTTP OTA running, flash the newly built firmware once via USB or local OTA. Subsequent updates will install over HTTP OTA automatically.

---

## Legacy Migration

If you are migrating from the previous ESPHome OTA Publisher add-on:
1. Open the **ESPHome OTA** panel.
2. Click **Import from Legacy Add-on**.
3. The migration tool reads `esphome/ota_server/registered.json`, copies existing binaries from `www/esphome_ota/` into private storage, and preserves all secret tokens and device slugs.
4. Stop or uninstall the legacy add-on once migration completes.

---

## Validation & Testing

Run the full automated test suite with pytest:
```bash
pytest tests/
```
For detailed live validation procedures in Home Assistant OS, see [docs/validation.ko.md](docs/validation.ko.md).

---

## License

This project is licensed under the MIT License.
