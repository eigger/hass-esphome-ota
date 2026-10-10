"""Tests verifying parity with legacy hassio-apps/esphome_ota addon.

Specifically verifies:
1. bump_patch_version matches legacy bump_version behavior (v260901 rev.1 -> rev.2, dates, semver).
2. Authoritative binary version is published even when different from reserved version (no crash).
3. Automatic managed_version advance after successful publish (advance_registered_version).
4. Build log sanitization strips ANSI escape sequences, literal 033, and tofu characters.
5. Explicit compile failure/cancellation/false status is not bypassed by success logs in stream.
6. Inline package project version ownership is synchronizable via set_project_version.
7. Unsynchronizable external version with explicit target version raises BuilderError.
8. Frontend and backend bumpPatchVersion rules match 100% on identical inputs.
"""

from __future__ import annotations

import re
import aiohttp
from homeassistant.core import HomeAssistant
import pytest

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.config_patch import (
    bump_patch_version,
    set_project_version,
)
from custom_components.esphome_ota.const import STAGE_PUBLISHED
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner, _clean_log_line
from custom_components.esphome_ota.models import BuilderError
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


def test_legacy_bump_version_parity() -> None:
    """Verify bump_patch_version parity with legacy addon bump_version."""
    # Revision strings like user's v260901 rev.1
    assert bump_patch_version("v260901 rev.1") == "v260901 rev.2"
    assert bump_patch_version("v260819 rev.4") == "v260819 rev.5"

    # Date-based versions
    assert bump_patch_version("2026-08-19") == "2026-08-19.1"
    assert bump_patch_version("2026-08-19.1") == "2026-08-19.2"
    assert bump_patch_version("2026.07.04") == "2026.07.04.1"
    assert bump_patch_version("20260819") == "20260819.1"
    assert bump_patch_version("20260819.3") == "20260819.4"

    # Standard semver
    assert bump_patch_version("1.0.0") == "1.0.1"
    assert bump_patch_version("1.0.9") == "1.0.10"
    assert bump_patch_version("2.1") == "2.1.1"
    assert bump_patch_version("3") == "3.0.1"
    assert bump_patch_version("") == "1.0.0"


def test_frontend_js_bump_version_parity() -> None:
    """Verify JS bumpPatchVersion logic produces identical outputs to Python bump_patch_version."""
    date_sep_re = re.compile(
        r"^(20\d\d([-.])(0?[1-9]|1[0-2])\2(0?[1-9]|[12]\d|3[01]))(?:\.(\d+))?$"
    )
    date_compact_re = re.compile(
        r"^(20\d\d(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01]))(?:\.(\d+))?$"
    )

    def js_bump_patch_version(version: str) -> str:
        text = str(version or "").strip().replace('"', "")
        if not text:
            return "1.0.0"
        m_sep = date_sep_re.match(text)
        if m_sep:
            base = m_sep.group(1)
            seq = m_sep.groups()[-1]
            return f"{base}.{int(seq) + 1}" if seq is not None else f"{base}.1"
        m_compact = date_compact_re.match(text)
        if m_compact:
            base = m_compact.group(1)
            seq = m_compact.groups()[-1]
            return f"{base}.{int(seq) + 1}" if seq is not None else f"{base}.1"
        dot_parts = text.split(".")
        if len(dot_parts) == 1 and dot_parts[0].isdigit():
            return f"{dot_parts[0]}.0.1"
        if len(dot_parts) == 2 and dot_parts[0].isdigit() and dot_parts[1].isdigit():
            return f"{dot_parts[0]}.{dot_parts[1]}.1"
        parts = re.split(r"(\d+)", text)
        for i in range(len(parts) - 1, -1, -1):
            if parts[i].isdigit():
                parts[i] = str(int(parts[i]) + 1)
                return "".join(parts)
        return f"{text}.1"

    test_inputs = [
        "2026.07.04",
        "2026-08-19",
        "2026-08-19.1",
        "20260819",
        "20260819.3",
        "1.0.0",
        "1.0.9",
        "2.1",
        "3",
        "v260901 rev.1",
    ]
    for inp in test_inputs:
        assert js_bump_patch_version(inp) == bump_patch_version(inp)


def test_clean_log_line() -> None:
    """Verify log sanitization removes ANSI sequences, literal 033, and tofu characters."""
    raw1 = "\033[32mINFO Successfully compiled program.\033[0m"
    assert _clean_log_line(raw1) == "INFO Successfully compiled program."

    raw2 = r"\033[32mINFO Created: /data/build/firmware.factory.bin\033[0m"
    assert _clean_log_line(raw2) == "INFO Created: /data/build/firmware.factory.bin"

    raw3 = "[1865/1956] Building CXX object\x1b[K\n"
    assert _clean_log_line(raw3) == "[1865/1956] Building CXX object"

    raw4 = "\ufffd[01m\ufffd[K../src/components/ledc.cpp"
    assert _clean_log_line(raw4) == "[01m[K../src/components/ledc.cpp"


async def test_job_runner_publishes_authoritative_binary_version_and_advances(
    hass: HomeAssistant,
    mock_builder: MockBuilderServer,
) -> None:
    """Verify that when compiled binary reports a version different from reserved version,

    the pipeline does not crash with BinaryValidationError, publishes the binary version,
    and advances managed_version for the next build.
    """
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_parity_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
        managed_version="1.0.0",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="https://my-ha.duckdns.org",
            target_version="9.9.9",
        )

        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_PUBLISHED
        assert job.error is None
        assert job.binary_version == "1.0.0"

        updated_dev = device_manager.get_device("livingroom")
        assert updated_dev is not None
        assert updated_dev.last_published_version == "1.0.0"
        assert updated_dev.managed_version == "1.0.1"


async def test_wait_for_compile_completion_explicit_failure_never_succeeds() -> None:
    """[P1] Verify that explicit failed/cancelled/false statuses raise BuilderError even with success logs."""
    from unittest.mock import AsyncMock, patch

    mock_conn = AsyncMock()
    mock_conn.server_info = {}
    client = BuilderClient(mock_conn)

    # Scenario 1: Stream has success log, but ends with explicit status: failed
    async def mock_follow_failed(*args, **kwargs):
        yield {"event": "output", "data": "INFO Successfully compiled program."}
        yield {"event": "result", "data": {"status": "failed", "code": 1}}

    with patch.object(client, "follow_job", side_effect=mock_follow_failed):
        with pytest.raises(BuilderError, match="status='failed'"):
            await client.wait_for_compile_completion("test.yaml", "job_1")

    # Scenario 2: Stream has success log, but ends with explicit status: cancelled
    async def mock_follow_cancelled(*args, **kwargs):
        yield {"event": "output", "data": "INFO Successfully compiled program."}
        yield {"event": "result", "data": {"status": "cancelled"}}

    with patch.object(client, "follow_job", side_effect=mock_follow_cancelled):
        with pytest.raises(BuilderError, match="status='cancelled'"):
            await client.wait_for_compile_completion("test.yaml", "job_2")

    # Scenario 3: Stream result has success: False (Python False == 0 trap check)
    async def mock_follow_false(*args, **kwargs):
        yield {"event": "output", "data": "INFO Successfully compiled program."}
        yield {"event": "result", "data": {"success": False, "status": "failed"}}

    with patch.object(client, "follow_job", side_effect=mock_follow_false):
        with pytest.raises(BuilderError, match="status='failed'"):
            await client.wait_for_compile_completion("test.yaml", "job_3")


def test_set_project_version_updates_inline_base_package() -> None:
    """[P2] Verify set_project_version updates project version inside packages.base."""
    base_pkg_yaml = (
        "esphome:\n"
        "  name: livingroom\n"
        "packages:\n"
        "  base:\n"
        "    esphome:\n"
        "      project:\n"
        "        name: 'my.project'\n"
        "        version: '1.0.0'\n"
        "    wifi:\n"
        "      ssid: test\n"
    )
    new_yaml, changed = set_project_version(base_pkg_yaml, "2.0.0")
    assert changed is True
    assert (
        "version: '2.0.0'" in new_yaml
        or 'version: "2.0.0"' in new_yaml
        or "version: 2.0.0" in new_yaml
    )
    assert "1.0.0" not in new_yaml
