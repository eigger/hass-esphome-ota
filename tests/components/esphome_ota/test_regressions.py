"""Direct regression test cases ported from legacy addon tests (test_token_ota, test_version_ownership, test_build_time)."""

from __future__ import annotations

import unittest

from custom_components.esphome_ota.config_patch import (
    own_project_version,
)
from custom_components.esphome_ota.firmware import (
    _parse_build_datetime,
)
from custom_components.esphome_ota.packages import (
    generate_inline_ota_yaml,
    project_name,
)


class TestBuildTimeRegressions(unittest.TestCase):
    """Port of test_build_time.py."""

    def test_normal_date(self) -> None:
        assert _parse_build_datetime("Aug 18 2026", "17:04:29") == "2026-08-18T17:04:29"

    def test_space_padded_day(self) -> None:
        assert _parse_build_datetime("Aug  8 2026", "07:04:09") == "2026-08-08T07:04:09"

    def test_all_months(self) -> None:
        months = [
            ("Jan", "01"),
            ("Feb", "02"),
            ("Mar", "03"),
            ("Apr", "04"),
            ("May", "05"),
            ("Jun", "06"),
            ("Jul", "07"),
            ("Aug", "08"),
            ("Sep", "09"),
            ("Oct", "10"),
            ("Nov", "11"),
            ("Dec", "12"),
        ]
        for name, num in months:
            with self.subTest(month=name):
                result = _parse_build_datetime(f"{name} 15 2026", "12:00:00")
                assert result == f"2026-{num}-15T12:00:00"

    def test_garbage_date_returns_none(self) -> None:
        assert _parse_build_datetime("not a date", "12:00:00") is None
        assert _parse_build_datetime("", "") is None
        assert _parse_build_datetime("Aug 18 2026", "") is None
        assert _parse_build_datetime("", "12:00:00") is None

    def test_bad_time_returns_none(self) -> None:
        assert _parse_build_datetime("Aug 18 2026", "bad") is None

    def test_unknown_month_returns_none(self) -> None:
        assert _parse_build_datetime("Xyz 18 2026", "12:00:00") is None


class TestVersionOwnershipRegressions(unittest.TestCase):
    """Port of test_version_ownership.py."""

    def test_ownership_detection(self) -> None:
        yaml_with_project = """
esphome:
  name: livingroom
  project:
    name: "me.livingroom"
    version: "2.0"
esp32:
  board: esp32dev
packages:
  ota: !include ota_server/devices/livingroom.yaml
"""
        assert own_project_version(yaml_with_project) == "2.0"

        yaml_no_project = """
esphome:
  name: bedroom
esp8266:
  board: d1_mini
packages:
  ota: !include ota_server/devices/bedroom.yaml
"""
        assert own_project_version(yaml_no_project) is None

    def test_framework_version_not_matched_as_project_version(self) -> None:
        yaml_fw = """
esphome:
  name: framework_node
esp32:
  board: esp32dev
  framework:
    type: esp-idf
    version: 5.1.2
"""
        assert own_project_version(yaml_fw) is None

    def test_project_name_truncation(self) -> None:
        assert project_name("livingroom") == "local.livingroom"
        long_node = "a" * 40
        assert len(project_name(long_node)) <= 32


class TestTokenOtaRegressions(unittest.TestCase):
    """Port of test_token_ota.py."""

    def test_packages_slug_substitution(self) -> None:
        token = "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
        slug = f"livingroom_{token}"
        yaml_out = generate_inline_ota_yaml(
            base_url="https://my-ha.duckdns.org",
            slug=slug,
            version="1.0.1",
            node="livingroom",
        )
        assert f'ota_slug: "{slug}"' in yaml_out
        assert "${ota_slug}.json" in yaml_out
        assert 'ota_base_url: "https://my-ha.duckdns.org"' in yaml_out
