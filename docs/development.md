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
# CI also installs the requirements of the HA components the tests load
# (ha-components: frontend panel_custom websocket_api http). Locally, `frontend` needs:
pip install "$(python -c 'import json,pathlib,homeassistant.components as c;print(json.loads((pathlib.Path(c.__file__).parent/"frontend/manifest.json").read_text())["requirements"][0])')"
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

## Adding dependencies

Follow the shared [dependency rules](https://github.com/eigger/hass-repo-standards/blob/ba9f3fad8b635c163fb44a4e91b1833cc4ab47b4/docs/dependencies.md):

- Runtime Python packages go in `manifest.json` `requirements`; Home Assistant domains in `dependencies` / `after_dependencies`.
- Test tools go in `requirements_test.txt` (the plugin pins `pytest-timeout`); lint tools in `requirements_lint.txt`.
- If tests load another HA component, add it to `ha-components` in `.github/workflows/tests.yml`.
- A new package needs its version, extras, marker, platform support and license reviewed, and tests against the real Home Assistant.
