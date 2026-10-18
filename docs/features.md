# ESPHome OTA features and architecture

[한국어](features.ko.md) | **English** | [Back to README](../README.md)

## Key features

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

## Architecture overview

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
