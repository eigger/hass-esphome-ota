# Development and testing

Rules follow [hass-repo-standards](https://github.com/eigger/hass-repo-standards) (details in Korean); see [STANDARDS.md](../STANDARDS.md) for the reviewed commit and exceptions.

This is a HACS custom integration. Its structure mirrors Home Assistant Core, but it makes no claim to be an official Core integration or to meet a Core quality tier.

## Layout

- `custom_components/esphome_ota/` — integration (domain `esphome_ota`)
- `tests/components/esphome_ota/` — tests that run against a real Home Assistant (`hass`, config entries, WebSocket/HTTP views). Only the ESPHome Builder network boundary is mocked.
- Design notes: [architecture.ko.md](architecture.ko.md) (Korean), live validation on HA OS: [validation.ko.md](validation.ko.md) (Korean)

## Local setup

Python 3.14 is required by the current Home Assistant test environment.

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_lint.txt -r requirements_test.txt
# CI also installs the pinned requirements of the HA components the tests load
# (frontend, panel_custom, websocket_api, http); install them locally the same way if imports fail.
python -m ruff check . && python -m ruff format --check .
python -m pytest tests/components/esphome_ota/ -v --timeout 120
```

## Verified environments

| Environment | Home Assistant | pytest-homeassistant-custom-component | Python | Status |
|---|---|---|---|---|
| Current (CI `current` job) | 2026.10.2 | 0.13.373 | 3.14 | tested |
| Declared minimum (`hacs.json`) | 2024.1.0 | none published for this exact version | 3.12 | **not supported by the code**, see below |

The code imports `StaticPathConfig` from `homeassistant.components.http` (panel registration), which does not exist in HA 2024.1.2, so the declared minimum of 2024.1.0 cannot be verified. The minimum was not raised automatically; changing it is a separate support-policy decision recorded in [STANDARDS.md](../STANDARDS.md).

The integration has no external Python requirements (`manifest.json` `requirements` is empty). Not verified: a real ESPHome Builder add-on on Home Assistant OS beyond [validation.ko.md](validation.ko.md).
