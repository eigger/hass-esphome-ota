"""Unit tests for BuilderClient operations and explicit completion enforcement."""

from __future__ import annotations

from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.models import BuilderError, ConfigConflictError
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_builder_client_operations(mock_builder: MockBuilderServer) -> None:
    """Test device listing, get config, update config with CAS, and validate."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # 1. list_devices
        devices = await client.list_devices()
        assert len(devices) == 2
        assert devices[0]["name"] == "livingroom"

        # 2. get_config
        cfg = await client.get_config("livingroom")
        assert "livingroom" in cfg

        # 3. update_config with valid CAS
        new_content = "esphome:\n  name: livingroom\n  # updated\n"
        await client.update_config("livingroom", new_content, expected=cfg)
        updated_cfg = await client.get_config("livingroom")
        assert updated_cfg == new_content

        # 4. update_config with conflicting CAS raises ConfigConflictError
        with pytest.raises(ConfigConflictError):
            await client.update_config(
                "livingroom", "conflict", expected="stale_expected_content"
            )

        # 5. validate_config
        val = await client.validate_config("livingroom")
        assert val.get("success") is True or val.get("valid") is True

        await conn.disconnect()


async def test_compile_explicit_completion_success(
    mock_builder: MockBuilderServer,
) -> None:
    """Test compile completes and explicitly checks for 'completed' status."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await client.start_compile("livingroom")
        assert isinstance(job_id, str) and len(job_id) > 0

        logs: list[str] = []
        status = await client.wait_for_compile_completion(
            "livingroom", job_id, on_output=logs.append
        )
        assert status == "completed"
        assert len(logs) >= 2
        assert any("Compiling" in line for line in logs)

        await conn.disconnect()


async def test_compile_rejection_on_unknown_or_failed_status(
    mock_builder: MockBuilderServer,
) -> None:
    """WORK_ORDER requirement: Explicit completion only, do NOT accept 'unknown'."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # 1. Simulated 'failed' status
        mock_builder.compile_status = "failed"
        job_id = await client.start_compile("livingroom")
        with pytest.raises(BuilderError, match="status='failed'"):
            await client.wait_for_compile_completion("livingroom", job_id)

        # 2. Simulated 'unknown' status
        mock_builder.compile_status = "unknown"
        job_id2 = await client.start_compile("livingroom")
        with pytest.raises(BuilderError, match="status='unknown'"):
            await client.wait_for_compile_completion("livingroom", job_id2)

        await conn.disconnect()


async def test_download_ota_firmware(mock_builder: MockBuilderServer) -> None:
    """Test downloading binary via single-use token."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        blob = await client.download_ota("livingroom")
        assert len(blob) == len(mock_builder.binary_blob)
        assert blob.startswith(b"\xe9")

        # Download failure on invalid token
        mock_builder.issued_download_token = "invalid-token"
        with pytest.raises(BuilderError, match="HTTP 401"):
            await client.download_ota("livingroom")

        await conn.disconnect()


async def test_get_jobs_operations(mock_builder: MockBuilderServer) -> None:
    """Test get_jobs queries firmware/get_jobs and correctly parses list and dict payloads."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        mock_builder.jobs["job_1"] = {
            "configuration": "livingroom.yaml",
            "status": "running",
            "type": "compile",
        }

        # 1. Standard list payload from server
        jobs = await client.get_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "job_1"
        assert jobs[0]["type"] == "compile"

        # 2. Dict payload with 'jobs' key fallback
        conn.command = AsyncMock(return_value={"jobs": [{"job_id": "job_2", "status": "completed"}]})  # type: ignore[method-assign]
        jobs_dict = await client.get_jobs()
        assert len(jobs_dict) == 1
        assert jobs_dict[0]["job_id"] == "job_2"

        await conn.disconnect()

