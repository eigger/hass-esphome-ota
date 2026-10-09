"""High-level client for the ESPHome Device Builder API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import aiohttp

from ..const import (
    COMPILE_TIMEOUT_SECONDS,
    DOWNLOAD_TIMEOUT_SECONDS,
    FIRMWARE_BIN,
    FIRMWARE_OTA_BIN,
)
from ..models import (
    BuilderConnectionError,
    BuilderError,
    BuilderTimeoutError,
    ConfigConflictError,
)
from .capabilities import BuilderCapabilities
from .connection import BuilderConnection

_LOGGER = logging.getLogger(__name__)


class BuilderClient:
    """Client implementing the ESPHome Builder documented protocol."""

    def __init__(self, connection: BuilderConnection) -> None:
        self.conn = connection
        self.capabilities = BuilderCapabilities.from_server_info(connection.server_info)

    @property
    def is_connected(self) -> bool:
        return self.conn.is_connected

    async def list_devices(self) -> list[dict[str, Any]]:
        """List devices known to ESPHome Builder."""
        result = await self.conn.command("devices/list")
        if isinstance(result, dict):
            return result.get("configured", [])
        if isinstance(result, list):
            return result
        return []

    async def get_config(self, configuration: str) -> str:
        """Fetch YAML configuration for a device."""
        result = await self.conn.command(
            "devices/get_config", {"configuration": configuration}
        )
        if isinstance(result, dict):
            return result.get("content", "")
        if isinstance(result, str):
            return result
        return ""

    async def update_config(
        self,
        configuration: str,
        content: str,
        expected: str | None = None,
    ) -> None:
        """Update YAML configuration using Compare-And-Swap (CAS).

        Raises:
            ConfigConflictError: If expected content does not match current content.
            BuilderError: On other builder errors.
        """
        args: dict[str, Any] = {
            "configuration": configuration,
            "content": content,
        }
        if expected is not None:
            args["expected"] = expected

        try:
            await self.conn.command("devices/update_config", args)
        except BuilderError as err:
            err_msg = str(err).lower()
            if "conflict" in err_msg or "mismatch" in err_msg or "expected" in err_msg:
                raise ConfigConflictError(
                    f"CAS conflict updating config for {configuration}: {err}"
                ) from err
            raise

    async def validate_config(
        self,
        configuration: str,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Validate device YAML configuration by waiting for full streaming completion."""
        last_result: dict[str, Any] = {}
        output_lines: list[str] = []

        async for frame in self.conn.stream(
            "devices/validate",
            {"configuration": configuration},
            timeout=timeout,
        ):
            event = frame.get("event")
            if event == "_heartbeat":
                continue
            if event == "output":
                data = frame.get("data", "")
                if isinstance(data, str):
                    output_lines.extend(data.splitlines())
            elif event == "result" or "result" in frame:
                res = frame.get("data") or frame.get("result") or frame
                if isinstance(res, dict):
                    last_result = res
                break

        # Check success and exit code
        success = last_result.get("success", True)
        code = last_result.get("code", last_result.get("exit_code", 0))
        if not success or code != 0:
            tail = "\n".join(output_lines[-10:])
            raise BuilderError(
                f"Configuration validation failed for {configuration} (exit code {code}): {tail}".strip()
            )
        return last_result

    async def start_compile(self, configuration: str) -> str:
        """Submit compile job and return job_id string immediately."""
        result = await self.conn.command(
            "firmware/compile", {"configuration": configuration}
        )
        job_id = None
        if isinstance(result, dict):
            job_id = result.get("job_id")
        if not job_id:
            raise BuilderError(
                f"ESPHome Builder did not return a job_id for {configuration}"
            )
        return str(job_id)

    async def follow_job(
        self,
        job_id: str,
        timeout: float = COMPILE_TIMEOUT_SECONDS,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream frames for a compile job until completion."""
        async for frame in self.conn.stream(
            "firmware/follow_job", {"job_id": job_id}, timeout=timeout
        ):
            yield frame

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Query state and details for a specific job."""
        result = await self.conn.command("firmware/get_job", {"job_id": job_id})
        return result if isinstance(result, dict) else {}

    async def get_jobs(self) -> list[dict[str, Any]]:
        """Query current or recently known jobs from ESPHome Builder."""
        result = await self.conn.command("firmware/get_jobs")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "jobs" in result and isinstance(result["jobs"], list):
            return result["jobs"]
        return []

    async def cancel_job(self, job_id: str) -> None:
        """Cancel a running compile job."""
        try:
            await self.conn.command("firmware/cancel", {"job_id": job_id})
        except BuilderError as err:
            _LOGGER.warning("Cancel job %s returned: %s", job_id, err)

    async def wait_for_compile_completion(
        self,
        configuration: str,
        job_id: str,
        on_output: Callable[[str], None] | None = None,
        timeout: float = COMPILE_TIMEOUT_SECONDS,
    ) -> str:
        """Stream compile job to explicit completion.

        Unlike legacy implementations, this explicitly requires status == 'completed'.
        Does NOT accept 'unknown'.
        """
        status: str | None = None
        async for frame in self.follow_job(job_id, timeout=timeout):
            event = frame.get("event")
            data = frame.get("data")
            if event == "_heartbeat":
                if on_output:
                    on_output(f"... still building (job {job_id}) ...")
                continue
            if event == "output" and on_output and isinstance(data, str):
                for line in data.splitlines():
                    on_output(line)
            elif event == "result" and isinstance(data, dict):
                status = data.get("status")
            elif isinstance(data, dict) and "status" in data:
                status = data["status"]

        # If stream completed without explicit status in frame, query get_job
        if not status:
            job_info = await self.get_job(job_id)
            status = job_info.get("status")

        _LOGGER.info("Compile of %s (job %s) ended with status=%s", configuration, job_id, status)
        if status != "completed":
            raise BuilderError(
                f"Compile of {configuration} did not complete successfully: status='{status}'"
            )

        return status

    async def get_binaries(self, configuration: str) -> list[dict[str, Any]]:
        """Get compiled binaries for a configuration."""
        result = await self.conn.command(
            "firmware/get_binaries", {"configuration": configuration}
        )
        return result if isinstance(result, list) else []

    async def resolve_ota_binary_file(
        self,
        configuration: str,
        platform_hint: str | None = None,
    ) -> str:
        """Resolve the appropriate OTA binary filename for a configuration.

        Queries Builder binaries list:
        1. Checks for binary explicitly marked with type == 'ota'
        2. If ESP8266, prefers 'firmware.bin'
        3. Checks for 'firmware.ota.bin'
        4. Checks for 'firmware.bin'
        5. Falls back based on platform_hint or default FIRMWARE_OTA_BIN
        """
        try:
            binaries = await self.get_binaries(configuration)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not query binaries for %s: %s", configuration, err)
            binaries = []

        is_esp8266 = bool(platform_hint and "8266" in platform_hint.lower())

        if binaries:
            # 1. Prefer explicit type == "ota"
            for b in binaries:
                if b.get("type") == "ota" and b.get("file"):
                    return str(b["file"])

            files = [str(b.get("file")) for b in binaries if b.get("file")]

            # 2. For ESP8266, firmware.bin is the standard OTA image
            if is_esp8266 and FIRMWARE_BIN in files:
                return FIRMWARE_BIN

            # 3. Look for standard firmware.ota.bin
            if FIRMWARE_OTA_BIN in files:
                return FIRMWARE_OTA_BIN

            # 4. Look for firmware.bin
            if FIRMWARE_BIN in files:
                return FIRMWARE_BIN

            # 5. Any .bin file
            for f in files:
                if f.endswith(".bin"):
                    return f

        if is_esp8266:
            return FIRMWARE_BIN

        return FIRMWARE_OTA_BIN

    async def has_ota_binary(
        self,
        configuration: str,
        platform_hint: str | None = None,
    ) -> bool:
        """Check if an OTA binary exists for configuration."""
        binaries = await self.get_binaries(configuration)
        if not binaries:
            return False
        files = {b.get("file") for b in binaries if b.get("file")}
        if FIRMWARE_OTA_BIN in files or FIRMWARE_BIN in files:
            return True
        return any(b.get("type") == "ota" for b in binaries)

    async def download_ota(
        self,
        configuration: str,
        filename: str | None = None,
        platform_hint: str | None = None,
    ) -> bytes:
        """Download OTA firmware binary for configuration using single-use token."""
        target_file = filename or await self.resolve_ota_binary_file(
            configuration=configuration,
            platform_hint=platform_hint,
        )
        token_info = await self.conn.command(
            "firmware/download_token",
            {"configuration": configuration, "file": target_file},
        )
        token = token_info.get("token") if isinstance(token_info, dict) else None
        if not token:
            raise BuilderError(f"No download token issued for {configuration} ({target_file})")

        url = f"{self.conn.base_url}/api/firmware/download"
        timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT_SECONDS)
        try:
            async with self.conn.session.get(
                url, params={"token": token}, timeout=timeout
            ) as resp:
                if resp.status != 200:
                    raise BuilderError(
                        f"Download of {target_file} for {configuration} failed with HTTP {resp.status}"
                    )
                blob = await resp.read()
        except asyncio.TimeoutError as err:
            raise BuilderTimeoutError(
                f"Download of {target_file} timed out after {DOWNLOAD_TIMEOUT_SECONDS}s"
            ) from err
        except aiohttp.ClientError as err:
            raise BuilderConnectionError(f"Failed to download firmware binary: {err}") from err

        _LOGGER.info("Downloaded %s (%s bytes) for %s", target_file, len(blob), configuration)
        return blob
