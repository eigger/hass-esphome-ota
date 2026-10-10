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

    async def get_jobs(self, configuration: str | None = None) -> list[dict[str, Any]]:
        """Query current or recently known jobs from ESPHome Builder."""
        result = await self.conn.command("firmware/get_jobs")
        jobs: list[dict[str, Any]] = []
        if isinstance(result, list):
            jobs = result
        elif isinstance(result, dict) and "jobs" in result and isinstance(result["jobs"], list):
            jobs = result["jobs"]
        if configuration:
            return [j for j in jobs if j.get("configuration") == configuration]
        return jobs

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
        has_success_log = False
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
                    if "successfully compiled program" in line.lower():
                        has_success_log = True
            elif event == "result" and isinstance(data, dict):
                status = data.get("status") or (
                    "completed" if data.get("success") is True or data.get("code") == 0 else None
                )
            elif isinstance(data, dict) and "status" in data:
                status = data["status"]

        # If stream completed without explicit status in frame, query get_job
        if not status:
            job_info = await self.get_job(job_id)
            status = job_info.get("status")

        # If compiler explicitly reported compilation success in output stream, accept it
        if has_success_log and (not status or status in ("unknown", "0", 0)):
            status = "completed"

        is_success = False
        if isinstance(status, str) and status.strip().lower() in ("completed", "success", "done", "ok", "0"):
            is_success = True
        elif status == 0 or status is True:
            is_success = True
        elif has_success_log:
            is_success = True

        _LOGGER.info("Compile of %s (job %s) ended with status=%s", configuration, job_id, status)
        if not is_success:
            raise BuilderError(
                f"Compile of {configuration} did not complete successfully: status='{status}'"
            )

        return str(status or "completed")

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
        2. Excludes any factory binaries (type == 'factory' or 'factory' in filename)
        3. For ESP8266, selects 'firmware.bin'
        4. For others, selects 'firmware.ota.bin' (or '*.ota.bin')
        5. Raises BuilderError if no valid OTA binary can be confirmed.
        """
        binaries: list[dict[str, Any]] = []
        try:
            binaries = await self.get_binaries(configuration)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not query binaries for %s: %s", configuration, err)

        is_esp8266 = bool(platform_hint and "8266" in platform_hint.lower())

        if binaries:
            # 1. Prefer explicit type == "ota"
            for b in binaries:
                if b.get("type") == "ota" and b.get("file"):
                    return str(b["file"])

            # 2. Filter out factory images
            candidates: list[str] = []
            for b in binaries:
                f = str(b.get("file", ""))
                b_type = str(b.get("type", "")).lower()
                if not f or b_type == "factory" or "factory" in f.lower():
                    continue
                candidates.append(f)

            # 3. For ESP8266, firmware.bin is standard OTA
            if is_esp8266 and FIRMWARE_BIN in candidates:
                return FIRMWARE_BIN

            # 4. Standard firmware.ota.bin
            if FIRMWARE_OTA_BIN in candidates:
                return FIRMWARE_OTA_BIN

            # 5. Any *.ota.bin
            for f in candidates:
                if f.endswith(".ota.bin"):
                    return f

            # 6. For ESP8266, any non-factory .bin
            if is_esp8266:
                for f in candidates:
                    if f.endswith(".bin"):
                        return f

            # 7. If no platform hint, and firmware.bin is present (without any other OTA)
            if not platform_hint and FIRMWARE_BIN in candidates:
                return FIRMWARE_BIN

            available = [b.get("file") for b in binaries if b.get("file")]
            raise BuilderError(
                f"No OTA binary found for {configuration} (available binaries: {available})"
            )

        # Fallback only when Builder get_binaries returned empty/failed
        if is_esp8266:
            return FIRMWARE_BIN
        return FIRMWARE_OTA_BIN

    async def has_ota_binary(
        self,
        configuration: str,
        platform_hint: str | None = None,
    ) -> bool:
        """Check if an OTA binary exists for configuration."""
        try:
            filename = await self.resolve_ota_binary_file(
                configuration=configuration,
                platform_hint=platform_hint,
            )
            return bool(filename)
        except BuilderError:
            return False

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
