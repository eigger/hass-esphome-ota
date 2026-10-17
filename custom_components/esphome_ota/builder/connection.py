"""WebSocket connection and multiplexing client for ESPHome Builder trusted listener."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, AsyncIterator, Callable

import aiohttp

from ..const import (
    STREAM_POLL_INTERVAL,
    WS_COMMAND_TIMEOUT,
    WS_CONNECT_TIMEOUT,
    WS_HEARTBEAT_INTERVAL,
)
from ..models import (
    BuilderAuthError,
    BuilderConnectionError,
    BuilderError,
    BuilderForbiddenError,
    BuilderTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

BACKOFF_STEPS = [2, 5, 10, 30, 60]


class BuilderConnection:
    """Manages an active WebSocket connection to the ESPHome Builder trusted listener.

    Multiplexes request-response commands and streaming commands over a single
    WebSocket using `message_id`.
    """

    def __init__(
        self,
        host: str,
        port: int,
        session: aiohttp.ClientSession,
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.session = session
        self.on_disconnect = on_disconnect
        self.server_info: dict[str, Any] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._next_id = 0
        self._connected = False
        self._closing = False
        self._reconnect_backoff_index = 0

    @property
    def is_connected(self) -> bool:
        """Return True if WebSocket is currently open."""
        return self._connected and self._ws is not None and not self._ws.closed

    @property
    def base_url(self) -> str:
        """Base HTTP URL for this connection."""
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        """Base WebSocket URL for this connection."""
        return f"ws://{self.host}:{self.port}/ws"

    async def connect(self) -> None:
        """Establish WebSocket connection and await handshake server info.

        Raises:
            BuilderAuthError: If builder requires authentication.
            BuilderConnectionError: If connection fails or 403 rejected.
        """
        self._closing = False
        url = self.ws_url
        _LOGGER.debug("Connecting to ESPHome Builder at %s", url)

        try:
            async with asyncio.timeout(WS_CONNECT_TIMEOUT):
                self._ws = await self.session.ws_connect(
                    url,
                    heartbeat=WS_HEARTBEAT_INTERVAL,
                    max_msg_size=16 * 1024 * 1024,
                )
        except aiohttp.WSServerHandshakeError as err:
            if err.status == 403:
                raise BuilderForbiddenError(
                    f"ESPHome Builder rejected connection (HTTP 403). "
                    f"Host {self.host} may not be recognized as trusted loopback."
                ) from err
            raise BuilderConnectionError(
                f"Failed to connect to ESPHome Builder at {url}: HTTP {err.status}"
            ) from err
        except TimeoutError as err:
            raise BuilderConnectionError(
                f"Timed out connecting to ESPHome Builder at {url}"
            ) from err
        except (aiohttp.ClientError, OSError) as err:
            raise BuilderConnectionError(
                f"Failed to reach ESPHome Builder at {url}: {err}"
            ) from err

        self._connected = True
        self._reconnect_backoff_index = 0
        self._reader_task = asyncio.create_task(self._read_loop())

        # Wait for unsolicited handshake frame containing server info
        self.server_info = await self._await_server_info()
        _LOGGER.debug("Connected to ESPHome Builder. Server info: %s", self.server_info)

        if self.server_info.get("requires_auth"):
            await self.disconnect()
            raise BuilderAuthError(
                "ESPHome Builder requires authentication. Expected trusted listener with no auth."
            )

    async def disconnect(self) -> None:
        """Cleanly close WebSocket and cancel background reader."""
        self._closing = True
        self._connected = False

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            # The reader re-raises its own cancellation; collect it here while still
            # propagating a cancellation of the caller itself.
            try:
                await asyncio.gather(self._reader_task, return_exceptions=True)
            finally:
                self._reader_task = None
                await self._close_socket()
        else:
            await self._close_socket()

    async def _close_socket(self) -> None:
        """Close the socket and fail waiting queues (also when cancelled)."""
        try:
            if self._ws and not self._ws.closed:
                await self._ws.close()
                self._ws = None
        finally:
            # Flush any waiting queues with error
            for queue in self._queues.values():
                queue.put_nowait(
                    {"error_code": "DISCONNECTED", "details": "Connection closed"}
                )
            self._queues.clear()

    async def _await_server_info(self) -> dict[str, Any]:
        """Wait for the initial unsolicited server info frame."""
        queue = self._queues.setdefault("", asyncio.Queue())
        try:
            return await asyncio.wait_for(queue.get(), timeout=20.0)
        except asyncio.TimeoutError as err:
            await self.disconnect()
            raise BuilderConnectionError(
                "Timed out waiting for Builder server info"
            ) from err

    async def _read_loop(self) -> None:
        """Background loop reading incoming frames and routing to message queues."""
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(msg.data)
                except ValueError:
                    _LOGGER.debug("Ignoring non-JSON WS frame: %s", msg.data)
                    continue

                # The unsolicited handshake frame has no message_id
                key = str(payload.get("message_id", ""))
                queue = self._queues.get(key)
                if queue:
                    queue.put_nowait(payload)
                else:
                    _LOGGER.debug("Unmatched frame for key '%s': %s", key, payload)

        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            if not self._closing:
                _LOGGER.warning("Builder WS connection read loop terminated: %s", err)
        finally:
            self._connected = False
            for q in list(self._queues.values()):
                q.put_nowait(
                    {
                        "error_code": "CONNECTION_LOST",
                        "details": "Builder connection closed",
                    }
                )
            if not self._closing and self.on_disconnect:
                try:
                    self.on_disconnect()
                except Exception as cb_err:  # noqa: BLE001
                    _LOGGER.debug("Error in on_disconnect callback: %s", cb_err)

    async def command(
        self,
        command_name: str,
        args: dict[str, Any] | None = None,
        timeout: float = WS_COMMAND_TIMEOUT,
    ) -> Any:
        """Execute a single request-response command and return result."""
        if not self.is_connected:
            raise BuilderConnectionError("Builder connection is closed")

        message_id, queue = await self._send_frame(command_name, args)
        try:
            payload = await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError as err:
            raise BuilderTimeoutError(
                f"Timed out after {timeout}s waiting for '{command_name}'"
            ) from err
        finally:
            self._queues.pop(message_id, None)

        return self._unwrap(command_name, payload)

    async def stream(
        self,
        command_name: str,
        args: dict[str, Any] | None = None,
        timeout: float = 45 * 60,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a streaming command yielding frames until termination or timeout."""
        if not self.is_connected:
            raise BuilderConnectionError("Builder connection is closed")

        message_id, queue = await self._send_frame(command_name, args)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise BuilderTimeoutError(
                        f"Timed out streaming '{command_name}' after {timeout}s"
                    )

                poll = min(STREAM_POLL_INTERVAL, remaining)
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=poll)
                except asyncio.TimeoutError:
                    if poll >= remaining:
                        raise BuilderTimeoutError(
                            f"Timed out streaming '{command_name}'"
                        ) from None
                    yield {"event": "_heartbeat"}
                    continue

                if "error_code" in payload:
                    error_code = payload.get("error_code")
                    details = payload.get("details", "")
                    if error_code in ("CONNECTION_LOST", "DISCONNECTED"):
                        raise BuilderConnectionError(
                            f"{command_name} failed: Builder connection lost ({details})"
                        )
                    raise BuilderError(
                        f"{command_name} failed: {error_code} {details}".strip()
                    )

                yield payload
                if payload.get("event") == "result" or "result" in payload:
                    return

        finally:
            self._queues.pop(message_id, None)

    async def _send_frame(
        self,
        command_name: str,
        args: dict[str, Any] | None,
    ) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        """Send a JSON command frame over the WebSocket."""
        if self._ws is None or self._ws.closed:
            raise BuilderConnectionError("WebSocket is not connected")

        self._next_id += 1
        message_id = str(self._next_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[message_id] = queue

        frame = {
            "command": command_name,
            "message_id": message_id,
            "args": args or {},
        }

        try:
            await self._ws.send_str(json.dumps(frame))
        except (ConnectionResetError, aiohttp.ClientError) as err:
            self._queues.pop(message_id, None)
            raise BuilderConnectionError(
                f"Lost connection to Builder while sending '{command_name}': {err}"
            ) from err

        return message_id, queue

    @staticmethod
    def _unwrap(command_name: str, payload: dict[str, Any]) -> Any:
        """Unwrap result from payload or raise BuilderError."""
        if "error_code" in payload:
            error_code = payload.get("error_code")
            details = payload.get("details", "")
            if error_code in ("CONNECTION_LOST", "DISCONNECTED"):
                raise BuilderConnectionError(
                    f"{command_name} failed: Builder connection lost ({details})"
                )
            raise BuilderError(f"{command_name} failed: {error_code} {details}".strip())
        return payload.get("result")

    def next_backoff_delay(self) -> float:
        """Compute the next reconnection backoff delay with random jitter."""
        step = BACKOFF_STEPS[min(self._reconnect_backoff_index, len(BACKOFF_STEPS) - 1)]
        self._reconnect_backoff_index += 1
        jitter = random.uniform(0.8, 1.2)  # noqa: S311
        return step * jitter
