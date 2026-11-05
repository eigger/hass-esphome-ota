"""Static checks of the panel frontend sources."""

from __future__ import annotations

import re
from pathlib import Path

_FRONTEND_DIR = (
    Path(__file__).parents[3] / "custom_components" / "esphome_ota" / "frontend"
)


def _i18n_keys(i18n_js: str, lang: str) -> set[str]:
    """Extract translation keys for a language block from i18n.js source."""
    match = re.search(
        rf"^\s{{2}}{lang}:\s*\{{(.*?)^\s{{2}}\}},",
        i18n_js,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"Missing {lang} translation block"
    return set(re.findall(r"^\s{4}(\w+):", match.group(1), re.MULTILINE))


def test_frontend_components() -> None:
    """The panel wires its dialogs and no longer ships the legacy import UI."""
    manager_js = (_FRONTEND_DIR / "manager.js").read_text(encoding="utf-8")
    device_dialog_js = (_FRONTEND_DIR / "device-dialog.js").read_text(encoding="utf-8")
    i18n_js = (_FRONTEND_DIR / "i18n.js").read_text(encoding="utf-8")

    assert 'import "./build-dialog.js";' in manager_js
    assert "<esphome-ota-build-dialog></esphome-ota-build-dialog>" in manager_js
    assert (_FRONTEND_DIR / "build-dialog.js").is_file()
    assert 'batch_build: "Build & Publish Selected"' in i18n_js
    assert "filter_managed" in i18n_js
    assert 'value="managed"' in manager_js
    assert "_filterDefaulted" in manager_js
    assert "_syncDefaultFilter" in manager_js
    assert "definePanelElement" in manager_js
    assert (_FRONTEND_DIR / "elements.js").is_file()
    assert "_getLatestJob" in manager_js
    assert "_getDeviceBadge" in manager_js
    assert "esphome_ota/remove_ota" in device_dialog_js
    assert "btn_remove_ota" in i18n_js

    # The legacy add-on import was removed.
    assert not (_FRONTEND_DIR / "migration-dialog.js").exists()
    for source in (manager_js, i18n_js):
        assert "migrat" not in source.lower()


def test_i18n_en_ko_key_parity() -> None:
    """Ensure English and Korean translation key sets stay in sync."""
    i18n_js = (_FRONTEND_DIR / "i18n.js").read_text(encoding="utf-8")
    en_keys = _i18n_keys(i18n_js, "en")
    ko_keys = _i18n_keys(i18n_js, "ko")
    assert en_keys == ko_keys, (
        f"en-only: {sorted(en_keys - ko_keys)}; ko-only: {sorted(ko_keys - en_keys)}"
    )
    assert "batch_build" in en_keys
