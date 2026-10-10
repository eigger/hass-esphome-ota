"""Unit tests for BuilderConnection WebSocket client."""

from __future__ import annotations


import aiohttp
import pytest

from custom_components.esphome_ota.builder.connection import (
    BACKOFF_STEPS,
    BuilderConnection,
)
from custom_components.esphome_ota.models import (
    BuilderAuthError,
    BuilderConnectionError,
    BuilderError,
)
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_successful_connection_and_handshake(
    mock_builder: MockBuilderServer,
) -> None:
    """Test connecting to loopback trusted listener with unsolicited server info."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        assert conn.is_connected
        assert conn.server_info.get("version") == "2026.10.0"
        assert conn.server_info.get("requires_auth") is False
        await conn.disconnect()
        assert not conn.is_connected


async def test_auth_required_rejection() -> None:
    """Test connection is rejected when builder requires authentication."""
    auth_server = MockBuilderServer(requires_auth=True)
    await auth_server.start()
    try:
        async with aiohttp.ClientSession() as session:
            conn = BuilderConnection("127.0.0.1", auth_server.port, session)
            with pytest.raises(BuilderAuthError):
                await conn.connect()
            assert not conn.is_connected
    finally:
        await auth_server.stop()


async def test_http_403_rejection() -> None:
    """Test connection fails with BuilderConnectionError on HTTP 403."""
    forbidden_server = MockBuilderServer(reject_403=True)
    await forbidden_server.start()
    try:
        async with aiohttp.ClientSession() as session:
            conn = BuilderConnection("127.0.0.1", forbidden_server.port, session)
            with pytest.raises(BuilderConnectionError):
                await conn.connect()
    finally:
        await forbidden_server.stop()


async def test_command_execution_and_error(mock_builder: MockBuilderServer) -> None:
    """Test command multiplexing and error unwrap."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()

        # Valid command
        res = await conn.command("devices/list")
        assert "configured" in res
        assert len(res["configured"]) == 2

        # Command with CAS conflict error
        with pytest.raises(BuilderError, match="CAS_CONFLICT"):
            await conn.command(
                "devices/update_config",
                {
                    "configuration": "livingroom",
                    "content": "new",
                    "expected": "wrong_expected",
                },
            )

        await conn.disconnect()


async def test_backoff_jitter() -> None:
    """Test exponential backoff progression."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", 1234, session)
        delays = [conn.next_backoff_delay() for _ in range(len(BACKOFF_STEPS) + 2)]
        assert len(delays) == len(BACKOFF_STEPS) + 2
        # Verify first step roughly 2s
        assert 1.5 <= delays[0] <= 2.5
        # Verify capped around 60s
        assert 45 <= delays[-1] <= 75
