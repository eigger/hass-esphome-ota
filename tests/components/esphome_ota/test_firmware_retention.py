"""Verify firmware archive retention against Home Assistant disk storage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import FormData
from homeassistant.core import HomeAssistant
from homeassistant.util.file import WriteError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.components.esphome_ota.conftest import MockBuilderServer


@pytest.fixture
def hass_config_dir(tmp_path: Path) -> str:
    """Keep the on-disk archive and store isolated from other tests."""
    return str(tmp_path)


@pytest.fixture
def hass_storage() -> dict:
    """Use real Home Assistant storage writes for retention checks."""
    return {}


async def test_firmware_archive_retention(
    hass: HomeAssistant,
    hass_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Prune after a saved upload and on reload, while preserving republish."""
    mock_config_entry.add_to_hass(hass)
    device_id = "retention"
    url = f"/api/esphome_ota/upload/{device_id}"

    async def upload(blob: bytes) -> None:
        form = FormData()
        form.add_field(
            "file",
            blob,
            filename="firmware.ota.bin",
            content_type="application/octet-stream",
        )
        response = await client.post(url, data=form)
        assert response.status == 200
        await response.read()

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        manager = mock_config_entry.runtime_data
        client = await hass_client()
        await manager.device_manager.async_register_or_update(
            device_id=device_id,
            configuration=f"{device_id}.yaml",
            name=device_id,
            friendly_name="Retention Test",
            target_platform="esp32",
        )

        first_blob = mock_builder.binary_blob
        await upload(first_blob)
        first = (await manager.storage.async_load_artifacts())[device_id]
        first_path = Path(first.private_path)
        assert first_path.is_file()

        # HA Store can swallow write failures, leaving the prior record on disk.
        with patch.object(
            manager.storage._artifact_store,
            "_async_write_data",
            side_effect=WriteError("simulated disk error"),
        ):
            await upload(first_blob + b"\x01")
        uncommitted = (await manager.storage.async_load_artifacts())[device_id]
        assert Path(uncommitted.private_path).is_file()
        assert first_path.is_file()

        current_blob = first_blob + b"\x02"
        await upload(current_blob)
        current = (await manager.storage.async_load_artifacts())[device_id]
        current_path = Path(current.private_path)
        assert list(current_path.parent.glob("*.bin")) == [current_path]

        unrelated = current_path.with_name("manual.bin")
        other_dir = current_path.parent.with_name("retention-other")
        other_file = other_dir / first_path.name

        def seed_existing_archives() -> None:
            first_path.write_bytes(first_blob)
            unrelated.write_bytes(b"manual")
            other_dir.mkdir(exist_ok=True)
            other_file.write_bytes(first_blob)

        await hass.async_add_executor_job(seed_existing_archives)
        lock = manager.device_manager.get_lock(device_id)
        async with lock:
            assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
            assert (
                mock_config_entry.runtime_data.device_manager.get_lock(device_id)
                is lock
            )
            assert first_path.is_file()

        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        manager = mock_config_entry.runtime_data
        assert not first_path.exists()
        assert unrelated.is_file()
        assert other_file.is_file()

        dev = manager.device_manager.get_device(device_id)
        assert dev is not None
        await manager.publisher.async_deactivate(dev.slug)
        republished = await manager.job_runner.async_republish(dev, current)
        assert Path(republished.public_bin_path).read_bytes() == current_blob
        assert Path(republished.private_path) == current_path
