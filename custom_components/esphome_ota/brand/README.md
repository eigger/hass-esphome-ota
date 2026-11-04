# ESPHome OTA brand assets

An original geometric smart-home circuit trace and OTA upload arrow icon drawn
by `scripts/generate_brand.py` on a dark navy rounded square, with a matching
cyan `ESPHome OTA` wordmark for the landscape logo. No third-party artwork is
used.

| File | Size | Purpose |
| --- | --- | --- |
| `icon.png` | 256 × 256 | Home Assistant and HACS icon |
| `icon@2x.png` | 512 × 512 | High-resolution icon |
| `logo.png` | 1200 × 256 | Landscape integration logo; README artwork |
| `logo@2x.png` | 2400 × 512 | High-resolution landscape logo |

All images are RGBA PNGs with transparent outer corners and backgrounds. These
sizes follow the [HA brand image guidelines](https://contributors.home-assistant.io/core/integrations/brands/).
Home Assistant 2026.3 and later serves these assets from the integration's local
`brand/` directory. The cyan wordmark works against light and dark backgrounds,
so separate dark variants are not required.

## Source and permission

The icon is drawn from geometric primitives in this repository's
`scripts/generate_brand.py` and is covered by the repository's MIT license
(Copyright (c) 2026 eigger). The wordmark is rendered with Pillow's bundled
Aileron Regular via
[`ImageFont.load_default`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.load_default).
[Aileron](https://dotcolon.net/font/aileron/) permits commercial use and is
released with no rights reserved. No font file is redistributed or loaded from
the system.

## Reproduce

Use Python 3.10 or newer and Pillow 12.3.0 (also supplied by HA 2026.10.2):

```sh
python -m pip install Pillow==12.3.0
python scripts/generate_brand.py
```

The script needs no network access and produces the same PNG bytes on every
run with that Pillow version.

SHA256 (Pillow 12.3.0):

- `icon@2x.png`: `ab8bd70e777ade79a8d4935b2e874b6ef766419dca37493d8ff3ba84f72c130d`
- `icon.png`: `876e635674596e1ee0546f5e30a06bfd7c7b047386ec178f9048ac8fe38b3aa7`
- `logo@2x.png`: `ee27eaf1db755c47b94170f57249196696177d2c696d96898190fb492e115970`
- `logo.png`: `719335ac50dd0b52a73a4501955f54fab2145c0a54a000e4d89890ebe05a07e8`

The local `brand/icon.png` is used by the
[HACS brands check](https://hacs.xyz/docs/publish/include/#check-brands).
These files do not imply inclusion in the HACS default list or HA brands
repository. README pages use `custom_components/esphome_ota/brand/logo.png`.
