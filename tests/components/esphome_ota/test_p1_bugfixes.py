"""Unit tests verifying fixes for the 8 P1 issues identified in review."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import yaml

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import (
    STAGE_PUBLISHED,
    STATUS_READY,
    STATUS_RECONNECTING,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import (
    BuilderError,
)
from custom_components.esphome_ota.packages import generate_inline_ota_yaml
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_p1_issue1_filename_extension_separation(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1] Builder requires full configuration filename with .yaml extension."""
    storage = StorageManager(hass)
    dm = DeviceManager(hass, storage)

    dm.update_builder_devices(
        [
            {
                "name": "livingroom",
                "configuration": "livingroom.yaml",
                "target_platform": "esp32",
            }
        ]
    )

    all_devs = dm.list_all()
    assert len(all_devs) == 1
    dev_item = all_devs[0]
    assert dev_item["device_id"] == "livingroom"
    assert dev_item["configuration"] == "livingroom.yaml"

    config_filename = dm.get_configuration("livingroom")
    assert config_filename == "livingroom.yaml"


async def test_p1_issue2_hex_string_job_id(mock_builder: MockBuilderServer) -> None:
    """[P1] Builder returns 12-char hex string job_id; client must not int() convert it."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await client.start_compile("livingroom.yaml")
        assert isinstance(job_id, str)
        # Verify it has hex / string characters and was not cast to int
        assert not job_id.isdigit()

        # Stream follow_job with string job_id
        frames = [f async for f in client.follow_job(job_id)]
        assert len(frames) >= 2
        assert any(f.get("event") == "result" for f in frames)

        await conn.disconnect()


def test_p1_issue3_packages_yaml_indentation_parsing() -> None:
    """[P1] Generated packages.esphome_ota block must have correct indentation.

    esphome.project must reside inside packages.esphome_ota, not as a top-level package.
    """
    snippet = generate_inline_ota_yaml(
        base_url="http://ha.local:8123",
        slug="livingroom_abc123",
        version="1.0.0",
        node="livingroom",
        use_project=True,
    )

    wrapped = f"packages:\n{snippet}"
    parsed = yaml.safe_load(wrapped)

    assert "packages" in parsed
    assert "esphome_ota" in parsed["packages"]
    # esphome must be inside esphome_ota, not a sibling package
    assert "esphome" not in parsed["packages"]
    assert "esphome" in parsed["packages"]["esphome_ota"]
    assert "project" in parsed["packages"]["esphome_ota"]["esphome"]
    assert (
        parsed["packages"]["esphome_ota"]["esphome"]["project"]["name"]
        == "local.livingroom"
    )
    assert parsed["packages"]["esphome_ota"]["esphome"]["project"]["version"] == "1.0.0"


async def test_p1_issue4_ws_subscribe_snapshot_event(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """[P1] subscribe command must dispatch initial snapshot as an event for subscribeMessage."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[
            MagicMock(
                slug=mock_config_entry.data["builder_slug"],
                name="Test Builder",
                host="127.0.0.1",
                port=mock_builder.port,
                source="dashboard",
                is_running=True,
            )
        ],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json({"id": 10, "type": "esphome_ota/subscribe"})

    # 1. Result acknowledge frame
    ack = await client.receive_json()
    assert ack["id"] == 10
    assert ack["type"] == "result"
    assert ack["success"] is True

    # 2. Snapshot event frame (what subscribeMessage callback actually receives)
    event_frame = await client.receive_json()
    assert event_frame["id"] == 10
    assert event_frame["type"] == "event"
    assert event_frame["event"]["event"] == "snapshot"
    assert "devices" in event_frame["event"]["data"]
    assert "status" in event_frame["event"]["data"]

    await client.close()
    await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_p1_issue5_auto_reconnect_loop(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1] OtaManager must automatically trigger reconnect on connection drop."""
    from custom_components.esphome_ota.manager import OtaManager
    from tests.components.esphome_ota.conftest import MockConfigEntry

    entry = MockConfigEntry(
        domain="esphome_ota",
        data={"builder_slug": "test_builder", "base_url": "http://ha.local:8123"},
    )

    manager = OtaManager(hass, entry)
    with patch.object(
        manager.resolver.discovery_adapter,
        "async_discover_all",
        return_value=[
            MagicMock(
                slug="test_builder",
                name="Test Builder",
                host="127.0.0.1",
                port=mock_builder.port,
                source="dashboard",
                is_running=True,
            )
        ],
    ):
        client = await manager.resolver.async_resolve()
        manager._attach_connection_listener(client)
        assert manager.resolver.status == STATUS_READY

        # Simulate disconnect callback
        dispatched_events: list[tuple[str, dict]] = []
        manager.add_subscriber(lambda e, d: dispatched_events.append((e, d)))

        client.conn.on_disconnect()
        assert manager.resolver.status == STATUS_RECONNECTING
        assert any(e == "status_changed" for e, _ in dispatched_events)
        assert manager._reconnect_task is not None

        # Clean up
        await manager.async_unload()


async def test_p1_issue6_validate_config_stream_completion() -> None:
    """[P1] validate_config must consume stream until final code and raise on non-zero exit."""
    mock_conn = MagicMock(spec=BuilderConnection)
    mock_conn.server_info = {}

    # Simulate streaming frames: log line, log line, exit with error code 1
    async def mock_stream_failure(*args, **kwargs):
        yield {"event": "output", "data": "INFO Compiling schema\n"}
        yield {"event": "output", "data": "ERROR Missing wifi configuration\n"}
        yield {"event": "result", "data": {"success": False, "code": 1}}

    mock_conn.stream = mock_stream_failure

    client = BuilderClient(mock_conn)
    with pytest.raises(BuilderError) as exc_info:
        await client.validate_config("broken.yaml")

    assert "exit code 1" in str(exc_info.value)
    assert "Missing wifi configuration" in str(exc_info.value)


async def test_p1_issue7_build_pipeline_syncs_bumped_version_to_yaml(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1] Version bumped before build (1.0.0 -> 1.0.1) must be written to YAML before compiling."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_bump_test")

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )
    # Simulate device had previous published version 1.0.0
    dev.last_published_version = "1.0.0"

    runner = JobRunner(hass, storage, device_manager, publisher)

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # In mock_builder, modify binary_blob to contain 1.0.1 version literal
        mock_builder.binary_blob = mock_builder.binary_blob.replace(
            b"version 1.0.0\x00", b"version 1.0.1\x00"
        )

        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="http://ha.local:8123",
        )

        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_PUBLISHED
        assert job.reserved_version == "1.0.1"
        assert job.binary_version == "1.0.1"

        # Verify YAML in builder received 1.0.1
        final_yaml = await client.get_config("livingroom.yaml")
        assert 'version: "1.0.1"' in final_yaml


async def test_build_pipeline_respects_explicit_target_version(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """User-provided target_version must override automatic patch bump."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_override_ver_test")

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )
    dev.last_published_version = "1.0.0"

    runner = JobRunner(hass, storage, device_manager, publisher)

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        mock_builder.binary_blob = mock_builder.binary_blob.replace(
            b"version 1.0.0\x00", b"version 2.5.0\x00"
        )

        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="http://ha.local:8123",
            target_version="2.5.0",
        )

        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_PUBLISHED
        assert job.reserved_version == "2.5.0"
        assert job.checkpoint.get("version_override") == "2.5.0"

        final_yaml = await client.get_config("livingroom.yaml")
        assert 'version: "2.5.0"' in final_yaml


async def test_build_pipeline_updates_yaml_project_version(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """When YAML owns project.version, an explicit target_version rewrites it."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_project_ver_test")

    mock_builder.configs["livingroom.yaml"] = """esphome:
  name: livingroom
  project:
    name: my.livingroom
    version: "1.0.0"
esp32:
  board: esp32dev
"""

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
        own_project_version="1.0.0",
    )

    runner = JobRunner(hass, storage, device_manager, publisher)

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        mock_builder.binary_blob = mock_builder.binary_blob.replace(
            b"version 1.0.0\x00", b"version 2.5.0\x00"
        )

        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="http://ha.local:8123",
            target_version="2.5.0",
        )

        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_PUBLISHED
        assert job.reserved_version == "2.5.0"
        assert device_manager.get_device("livingroom").own_project_version == "2.5.0"

        final_yaml = await client.get_config("livingroom.yaml")
        assert 'version: "2.5.0"' in final_yaml
        assert 'version: "1.0.0"' not in final_yaml


async def test_p1_issue8_prepare_ota_includes_cas_expected(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """[P1] prepare_ota must return expected/original for CAS protection in apply_ota."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[
            MagicMock(
                slug=mock_config_entry.data["builder_slug"],
                name="Test Builder",
                host="127.0.0.1",
                port=mock_builder.port,
                source="dashboard",
                is_running=True,
            )
        ],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    ws = await hass_ws_client(hass)

    # 1. Prepare OTA
    await ws.send_json(
        {"id": 20, "type": "esphome_ota/prepare_ota", "device_id": "livingroom"}
    )
    res = await ws.receive_json()
    assert res["success"] is True
    assert "expected" in res["result"]
    assert "original" in res["result"]
    expected_content = res["result"]["expected"]
    modified_content = res["result"]["modified"]

    # 2. Apply OTA with matching expected succeeds
    await ws.send_json(
        {
            "id": 21,
            "type": "esphome_ota/apply_ota",
            "device_id": "livingroom",
            "content": modified_content,
            "expected": expected_content,
        }
    )
    apply_res = await ws.receive_json()
    assert apply_res["success"] is True

    # 3. Apply OTA with mismatched expected fails with CAS conflict
    await ws.send_json(
        {
            "id": 22,
            "type": "esphome_ota/apply_ota",
            "device_id": "livingroom",
            "content": modified_content,
            "expected": "stale_yaml_content_from_concurrent_edit",
        }
    )
    conflict_res = await ws.receive_json()
    assert conflict_res["success"] is False
    assert conflict_res["error"]["code"] == "apply_failed"

    await ws.close()
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
