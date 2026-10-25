"""Pytest configuration and fixtures for ESPHome OTA tests."""

from __future__ import annotations

# <!-- hass-standards:domain-fixtures:start -->
# Use pytest_homeassistant_custom_component.common.MockConfigEntry for
# mock_config_entry when the integration uses config entries.
# Define mock_client only when an external communication client is present.
# Mock external communication boundaries, never Home Assistant core modules.
# Keep integration-specific fixtures below this managed block.
# <!-- hass-standards:domain-fixtures:end -->


import json
import shutil
import uuid
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import pytest
from aiohttp import web
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_NAME,
    CONF_BUILDER_SLUG,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def clean_public_www_dir(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Keep published files from leaking between tests (the config dir is shared)."""
    if "hass" not in request.fixturenames:
        yield
        return
    hass = request.getfixturevalue("hass")
    www = Path(hass.config.path("www"))
    shutil.rmtree(www, ignore_errors=True)
    yield
    shutil.rmtree(www, ignore_errors=True)


@pytest.fixture(autouse=True)
def enable_socket_for_tests(socket_enabled: None) -> None:
    """Allow loopback sockets for mock builder server tests."""


class MockBuilderServer:
    """Simulates an ESPHome Builder server speaking the WebSocket and HTTP download protocols."""

    def __init__(self, requires_auth: bool = False, reject_403: bool = False) -> None:
        self.requires_auth = requires_auth
        self.reject_403 = reject_403
        self.app = web.Application()
        self.app.router.add_get("/ws", self._ws_handler)
        self.app.router.add_get("/api/firmware/download", self._download_handler)
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.port: int = 0
        self.configs: dict[str, str] = {
            "livingroom.yaml": "esphome:\n  name: livingroom\nesp32:\n  board: esp32dev\n",
            "livingroom": "esphome:\n  name: livingroom\nesp32:\n  board: esp32dev\n",
            "bedroom.yaml": "esphome:\n  name: bedroom\n  project:\n    name: my.bedroom\n    version: '2.1.0'\nesp32:\n  board: esp32dev\n",
            "bedroom": "esphome:\n  name: bedroom\n  project:\n    name: my.bedroom\n    version: '2.1.0'\nesp32:\n  board: esp32dev\n",
        }
        self.jobs: dict[str, dict[str, Any]] = {}
        self.compile_status = "completed"
        self.issued_download_token = "valid-token-123"
        self.expected_download_token = "valid-token-123"
        self.binaries: list[dict[str, Any]] | None = None
        self.last_download_token_args: dict[str, Any] | None = None
        self.binary_blob = (
            b"\xe9\x00\x00\x00"  # Magic + dummy
            + b"\x00" * 8
            + b"\x00\x00"  # Chip ID 0 = ESP32 at offset 12
            + b"\x00" * 5
            + b"\x00\x00\x00\x00"  # offset 19-22 zero
            + b"\x00"  # offset 23 <= 1
            + b"\x00" * 8
            + b"\x32\x54\xcd\xab"  # offset 0x20 app desc magic
            + b"\x00" * 12
            + b"2026.10.0".ljust(32, b"\x00")  # offset 0x30 framework ver
            + b"livingroom".ljust(32, b"\x00")  # offset 0x50 proj name
            + b"12:00:00".ljust(16, b"\x00")  # offset 0x70 time
            + b"Oct  9 2026".ljust(16, b"\x00")  # offset 0x80 date
            + b"v5.1.2".ljust(32, b"\x00")  # offset 0x90 idf ver
            + b"\x00" * 200
            + b"Project local.livingroom version 1.0.0\x00"
            + b"\x00" * 1024
        )
        self.last_download_token = "valid-token-123"

        self.websockets: set[web.WebSocketResponse] = set()

    async def start(self) -> int:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        # Retrieve allocated port
        sockets = self.site._server.sockets  # type: ignore[attr-defined]
        self.port = sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        for ws in list(self.websockets):
            await ws.close()
        self.websockets.clear()
        if self.runner:
            await self.runner.cleanup()

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        if self.reject_403:
            return web.Response(status=403, text="Forbidden")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.websockets.add(ws)

        # 1. Unsolicited server info frame
        server_info = {
            "version": "2026.10.0",
            "name": "ESPHome Device Builder",
            "requires_auth": self.requires_auth,
            "port": 6052,
        }
        await ws.send_str(json.dumps(server_info))

        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            payload = json.loads(msg.data)
            cmd = payload.get("command")
            msg_id = payload.get("message_id")
            args = payload.get("args", {})

            if cmd == "devices/list":
                reply = {
                    "message_id": msg_id,
                    "result": {
                        "configured": [
                            {
                                "name": "livingroom",
                                "configuration": "livingroom.yaml",
                                "target_platform": "esp32",
                                "current_version": "2026.10.0",
                            },
                            {
                                "name": "bedroom",
                                "configuration": "bedroom.yaml",
                                "target_platform": "esp32",
                                "current_version": "2.1.0",
                            },
                        ]
                    },
                }
                await ws.send_str(json.dumps(reply))

            elif cmd == "devices/get_config":
                cfg_name = args.get("configuration", "")
                content = self.configs.get(cfg_name, "")
                reply = {
                    "message_id": msg_id,
                    "result": {"content": content},
                }
                await ws.send_str(json.dumps(reply))

            elif cmd == "devices/update_config":
                cfg_name = args.get("configuration", "")
                content = args.get("content", "")
                expected = args.get("expected")
                current = self.configs.get(cfg_name, "")
                if expected is not None and expected != current:
                    reply = {
                        "message_id": msg_id,
                        "error_code": "CAS_CONFLICT",
                        "details": "Expected content does not match current content",
                    }
                else:
                    self.configs[cfg_name] = content
                    reply = {
                        "message_id": msg_id,
                        "result": {"success": True},
                    }
                await ws.send_str(json.dumps(reply))

            elif cmd == "devices/validate":
                await ws.send_str(
                    json.dumps(
                        {
                            "message_id": msg_id,
                            "event": "output",
                            "data": "INFO Reading configuration...\n",
                        }
                    )
                )
                await ws.send_str(
                    json.dumps(
                        {
                            "message_id": msg_id,
                            "event": "result",
                            "data": {"success": True, "code": 0},
                        }
                    )
                )

            elif cmd == "firmware/compile":
                job_id = f"c{uuid.uuid4().hex[:11]}"
                self.jobs[job_id] = {
                    "status": self.compile_status,
                    "configuration": args.get("configuration"),
                }
                reply = {
                    "message_id": msg_id,
                    "result": {"job_id": job_id},
                }
                await ws.send_str(json.dumps(reply))

            elif cmd == "firmware/follow_job":
                job_id = args.get("job_id")
                # Send log frames
                await ws.send_str(
                    json.dumps(
                        {
                            "message_id": msg_id,
                            "event": "output",
                            "data": "Compiling .pioenvs/livingroom/src/main.cpp.o\n",
                        }
                    )
                )
                await ws.send_str(
                    json.dumps(
                        {
                            "message_id": msg_id,
                            "event": "output",
                            "data": "Generating firmware.ota.bin\n",
                        }
                    )
                )
                # Send terminal result frame
                status = self.jobs.get(job_id, {}).get("status", self.compile_status)
                await ws.send_str(
                    json.dumps(
                        {
                            "message_id": msg_id,
                            "event": "result",
                            "data": {"status": status},
                        }
                    )
                )

            elif cmd == "firmware/get_job":
                job_id = args.get("job_id")
                status = self.jobs.get(job_id, {}).get("status", self.compile_status)
                reply = {
                    "message_id": msg_id,
                    "result": {"status": status, "job_id": job_id},
                }
                await ws.send_str(json.dumps(reply))

            elif cmd == "firmware/get_jobs":
                job_list = [
                    {
                        "job_id": jid,
                        "configuration": jdata.get("configuration"),
                        "status": jdata.get("status"),
                        "type": jdata.get("type", "compile"),
                        "job_type": jdata.get("job_type", jdata.get("type", "compile")),
                        "created_at": jdata.get(
                            "created_at", datetime.now(timezone.utc).isoformat()
                        ),
                    }
                    for jid, jdata in self.jobs.items()
                ]
                reply = {
                    "message_id": msg_id,
                    "result": job_list,
                }
                await ws.send_str(json.dumps(reply))

            elif cmd == "firmware/cancel":
                job_id = args.get("job_id")
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "cancelled"
                reply = {
                    "message_id": msg_id,
                    "result": {"success": True},
                }
                await ws.send_str(json.dumps(reply))

            elif cmd == "firmware/get_binaries":
                bin_list = (
                    self.binaries
                    if self.binaries is not None
                    else [{"file": "firmware.ota.bin", "size": len(self.binary_blob)}]
                )
                reply = {
                    "message_id": msg_id,
                    "result": bin_list,
                }
                await ws.send_str(json.dumps(reply))

            elif cmd == "firmware/download_token":
                self.last_download_token_args = args
                reply = {
                    "message_id": msg_id,
                    "result": {"token": self.issued_download_token},
                }
                await ws.send_str(json.dumps(reply))

        self.websockets.discard(ws)
        return ws

    async def _download_handler(self, request: web.Request) -> web.Response:
        token = request.query.get("token")
        if token != self.expected_download_token:
            return web.Response(status=401, text="Invalid download token")
        return web.Response(
            body=self.binary_blob,
            content_type="application/octet-stream",
        )


@pytest.fixture
async def mock_builder() -> AsyncGenerator[MockBuilderServer, None]:
    """Provide a running mock ESPHome Builder server."""
    server = MockBuilderServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def mock_config_entry(mock_builder: MockBuilderServer) -> MockConfigEntry:
    """Provide a configured MockConfigEntry pointing to the mock builder."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="esphome_builder_test",
        title="ESPHome OTA Test",
        data={
            CONF_BUILDER_SLUG: "5c53de3b_esphome",
            CONF_BUILDER_NAME: "ESPHome Test",
            CONF_BASE_URL: "https://my-ha.duckdns.org",
        },
        options={
            CONF_BASE_URL: "https://my-ha.duckdns.org",
            CONF_AUTO_CLEANUP_HOURS: 12,
        },
    )
