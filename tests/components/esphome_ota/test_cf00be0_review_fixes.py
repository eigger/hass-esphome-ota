"""Unit and regression tests for cf00be0 review fixes.

Issues covered:
1. [P1] Cancelled job's firmware published belatedly by executor thread (jobs.py:708, publisher.py:156)
   - Executor thread cancellation check right before and after manifest finalization.
   - Automatic immediate unlinking of public artifacts if cancelled or unloaded.
   - Integration unload marks publisher unloaded and stops public file creation.
2. [P2] Post-installation builder selection when multiple candidates are discovered (resolver.py:61, config_flow.py:167)
   - OptionsFlow provides candidate selection dropdown and syncs to config entry data/options.
   - OptionsFlow supports selecting 'auto' to revert to automatic discovery.
   - WebSocket API 'esphome_ota/select_builder' and 'esphome_ota/reconnect' (with slug parameter)
     allow selecting candidates and transitioning from selection_required to ready.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_NAME,
    CONF_BUILDER_SLUG,
    DOMAIN,
    STAGE_CANCELLED,
    STATUS_READY,
    STATUS_SELECTION_REQUIRED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.manager import OtaManager
from custom_components.esphome_ota.models import (
    BuilderCandidate,
    EsphomeOtaError,
)
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ESP32_APP_DESC_MAGIC = b"\xab\xcd\x12\x00"


def _make_valid_esp32_bin(version: str = "1.0.0") -> bytes:
    """Create a minimal valid ESP32 binary with esp_app_desc_t."""
    blob = bytearray(b"\x00" * 2048)
    blob[0] = 0xE9
    app_desc = bytearray(256)
    app_desc[0:4] = ESP32_APP_DESC_MAGIC
    v_bytes = version.encode("ascii")[:31]
    app_desc[16 : 16 + len(v_bytes)] = v_bytes
    blob[32 : 32 + 256] = app_desc
    return bytes(blob)


# ---------------------------------------------------------------------------
# Issue 1: Cancelled job's firmware published belatedly by executor thread
# ---------------------------------------------------------------------------

async def test_issue1_publisher_cleans_up_on_cancellation(hass: HomeAssistant) -> None:
    """[P1] ArtifactPublisher._publish_sync aborts and cleans up public files when check_cancelled is True."""
    publisher = ArtifactPublisher(hass, publish_dir="test_pub_cancel")
    blob = _make_valid_esp32_bin("1.0.1")
    info = inspect_binary(blob, target_platform="esp32", expected_chip="ESP32")

    # When check_cancelled returns True before publication
    with pytest.raises(EsphomeOtaError, match="pipeline job was cancelled"):
        await publisher.async_publish(
            device_id="dev1",
            configuration="dev1.yaml",
            slug="dev1",
            blob=blob,
            info=info,
            check_cancelled=lambda: True,
        )

    # Verify no public files exist
    assert not (publisher.www_dir / "dev1.ota.bin").exists()
    assert not (publisher.www_dir / "dev1.ota.bin.md5").exists()
    assert not (publisher.www_dir / "dev1.json").exists()


async def test_issue1_publisher_cleans_up_on_unload(hass: HomeAssistant) -> None:
    """[P1] ArtifactPublisher._publish_sync aborts and cleans up if publisher was marked unloaded."""
    publisher = ArtifactPublisher(hass, publish_dir="test_pub_unload")
    publisher.async_unload()
    blob = _make_valid_esp32_bin("1.0.1")
    info = inspect_binary(blob, target_platform="esp32", expected_chip="ESP32")

    with pytest.raises(EsphomeOtaError, match="integration is unloaded"):
        await publisher.async_publish(
            device_id="dev2",
            configuration="dev2.yaml",
            slug="dev2",
            blob=blob,
            info=info,
        )

    assert not (publisher.www_dir / "dev2.ota.bin").exists()
    assert not (publisher.www_dir / "dev2.json").exists()


async def test_issue1_delayed_executor_thread_does_not_publish_when_cancelled(
    hass: HomeAssistant,
    mock_builder: MockBuilderServer,
) -> None:
    """[P1] If executor publish thread is delayed and the job is cancelled, the thread aborts without leaving public files."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="test_delayed_pub")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
        target_platform="esp32",
    )

    thread_entered = None
    thread_release = None
    import threading

    thread_entered = threading.Event()
    thread_release = threading.Event()

    original_publish_sync = publisher._publish_sync

    def _delayed_publish_sync(*args: Any, **kwargs: Any) -> Any:
        # Signal that executor thread reached publish
        thread_entered.set()
        # Wait until test cancels the job
        thread_release.wait(timeout=5.0)
        return original_publish_sync(*args, **kwargs)

    publisher._publish_sync = _delayed_publish_sync  # type: ignore[assignment]

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="https://ha.local",
        )

        # Wait until executor thread starts publishing
        for _ in range(50):
            if thread_entered.is_set():
                break
            await asyncio.sleep(0.05)

        assert thread_entered.is_set()

        # Cancel the pipeline job while executor thread is paused
        await runner.async_cancel_job(job_id, client)
        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_CANCELLED

        # Release executor thread
        thread_release.set()
        await asyncio.sleep(0.1)

        # Ensure public files were NOT created or left on disk
        public_bin = publisher.www_dir / f"{dev.slug}.ota.bin"
        public_manifest = publisher.www_dir / f"{dev.slug}.json"
        assert not public_bin.exists()
        assert not public_manifest.exists()

        # Ensure no published artifact was recorded in storage
        artifacts = await storage.async_load_artifacts()
        assert dev.device_id not in artifacts


# ---------------------------------------------------------------------------
# Issue 2: Post-installation builder selection when multiple candidates found
# ---------------------------------------------------------------------------

async def test_issue2_options_flow_builder_selection(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """[P2] OptionsFlow presents candidate choices and persists selection to config entry."""
    mock_config_entry.add_to_hass(hass)

    candidates = [
        BuilderCandidate(
            slug="5c53de3b_esphome",
            name="ESPHome Core",
            host="127.0.0.1",
            port=6052,
            source="supervisor_addon",
        ),
        BuilderCandidate(
            slug="esphome_beta",
            name="ESPHome Beta",
            host="127.0.0.1",
            port=6053,
            source="supervisor_addon",
        ),
    ]

    with patch(
        "custom_components.esphome_ota.config_flow.HaDiscoveryAdapter.async_discover_all",
        return_value=candidates,
    ):
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "init"

        # Verify builder slug is in schema
        schema = result["data_schema"].schema
        slug_keys = [k for k in schema if str(k) == CONF_BUILDER_SLUG or getattr(k, "schema", None) == CONF_BUILDER_SLUG]
        assert len(slug_keys) == 1

        # Submit selection of "esphome_beta"
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_BASE_URL: "https://my-ha.duckdns.org",
                CONF_AUTO_CLEANUP_HOURS: 48,
                CONF_BUILDER_SLUG: "esphome_beta",
            },
        )
        assert result2["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_BUILDER_SLUG] == "esphome_beta"

        # Verify entry data was updated with slug and name
        assert mock_config_entry.data.get(CONF_BUILDER_SLUG) == "esphome_beta"
        assert mock_config_entry.data.get(CONF_BUILDER_NAME) == "ESPHome Beta"


async def test_issue2_options_flow_revert_to_auto(
    hass: HomeAssistant,
) -> None:
    """[P2] Selecting 'auto' in OptionsFlow clears specific builder slug from config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BASE_URL: "https://my-ha.duckdns.org",
            CONF_BUILDER_SLUG: "esphome_beta",
            CONF_BUILDER_NAME: "ESPHome Beta",
        },
        options={
            CONF_BUILDER_SLUG: "esphome_beta",
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.config_flow.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is data_entry_flow.FlowResultType.FORM

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_BASE_URL: "https://my-ha.duckdns.org",
                CONF_AUTO_CLEANUP_HOURS: 24,
                CONF_BUILDER_SLUG: "auto",
            },
        )
        assert result2["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
        assert CONF_BUILDER_SLUG not in entry.data


async def test_issue2_websocket_select_builder_resolves(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """[P2] WebSocket esphome_ota/select_builder persists selection and connects."""
    # Entry with no initial builder selection
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: "https://ha.local"},
        options={},
    )
    entry.add_to_hass(hass)

    candidate1 = BuilderCandidate(
        slug="candidate_dummy",
        name="Dummy Builder",
        host="127.0.0.1",
        port=9999,
        source="supervisor_addon",
    )
    candidate2 = BuilderCandidate(
        slug="5c53de3b_esphome",
        name="ESPHome Core",
        host="127.0.0.1",
        port=mock_builder.port,
        source="supervisor_addon",
        is_running=True,
    )

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[candidate1, candidate2],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        manager: OtaManager = hass.data[DOMAIN]["manager"]
        # With multiple candidates and no saved selection, status is selection_required
        assert manager.resolver.status == STATUS_SELECTION_REQUIRED

        client = await hass_ws_client(hass)

        # Call esphome_ota/select_builder with 5c53de3b_esphome
        await client.send_json(
            {
                "id": 1,
                "type": "esphome_ota/select_builder",
                "slug": "5c53de3b_esphome",
            }
        )
        resp = await client.receive_json()
        assert resp["success"] is True
        assert resp["result"]["status"] == STATUS_READY
        assert resp["result"]["selected"] == "5c53de3b_esphome"

        # Verify manager resolver is connected
        assert manager.resolver.status == STATUS_READY
        assert manager.resolver.active_candidate is not None
        assert manager.resolver.active_candidate.slug == "5c53de3b_esphome"

        # Verify entry data updated
        assert entry.data.get(CONF_BUILDER_SLUG) == "5c53de3b_esphome"

        await client.close()
        await hass.config_entries.async_unload(entry.entry_id)


async def test_issue2_websocket_reconnect_with_slug(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_builder: MockBuilderServer,
) -> None:
    """[P2] WebSocket esphome_ota/reconnect with optional slug parameter selects builder."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: "https://ha.local"},
        options={},
    )
    entry.add_to_hass(hass)

    cand = BuilderCandidate(
        slug="5c53de3b_esphome",
        name="ESPHome Core",
        host="127.0.0.1",
        port=mock_builder.port,
        source="supervisor_addon",
        is_running=True,
    )

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[
            cand,
            BuilderCandidate(
                slug="other",
                name="Other",
                host="1.2.3.4",
                port=6052,
                source="supervisor_addon",
            ),
        ],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        manager: OtaManager = hass.data[DOMAIN]["manager"]
        assert manager.resolver.status == STATUS_SELECTION_REQUIRED

        client = await hass_ws_client(hass)
        await client.send_json(
            {
                "id": 2,
                "type": "esphome_ota/reconnect",
                "slug": "5c53de3b_esphome",
            }
        )
        resp = await client.receive_json()
        assert resp["success"] is True
        assert resp["result"]["status"] == STATUS_READY
        assert manager.resolver.status == STATUS_READY

        await client.close()
        await hass.config_entries.async_unload(entry.entry_id)
