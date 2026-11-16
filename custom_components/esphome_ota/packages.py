"""Generates ESPHome YAML package configurations for HTTP OTA."""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

from .const import DEFAULT_PUBLISH_DIR

_PROJECT_NAME_MAX = 32

NODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}\Z")
# The public firmware URL is served from /local/ without authentication, so the
# token is its only protection: require at least 128 bits of hex entropy.
TOKEN_MIN_LENGTH = 32
TOKEN_RE = re.compile(r"^[0-9a-f]{32,64}\Z")
VERSION_RE = re.compile(r"^[^\x00-\x1f\x7f\"'\\]{1,64}\Z")
_DEVICE_ID_RE = re.compile(r"^[^\x00-\x1f\x7f/\\]{1,128}\Z")


def is_valid_token(value: object) -> bool:
    """Return True if ``value`` is a strong public-URL token (32-64 lowercase hex)."""
    return isinstance(value, str) and bool(TOKEN_RE.match(value))


def generate_token() -> str:
    """Return a fresh random public-URL token (32 hex characters)."""
    return secrets.token_hex(TOKEN_MIN_LENGTH // 2)


def public_slug(name: str, token: str) -> str:
    """Return the public slug ``{name}_{token}`` for a validated token."""
    if not is_valid_token(token):
        raise ValueError("A public slug requires a random token of 32+ hex characters")
    return f"{name}_{token}"


def is_valid_device_id(value: str) -> bool:
    """Return True if ``value`` is safe to use as a device ID / file stem."""
    return (
        bool(_DEVICE_ID_RE.match(value))
        and ".." not in value
        and value.strip(" .") != ""
    )


def yaml_dq(value: str) -> str:
    """Return ``value`` as a double-quoted YAML scalar with escaping."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r")
    return f'"{escaped}"'


# Keys of integration-owned slug secrets. The prefix is deliberately NOT an
# extension of the legacy prefix below: every 1.7.0b0/b1 key starts with
# ``esphome_ota_slug_`` while every key now starts with ``esphome_ota_cfg_``
# (they differ at the 13th character, ``s`` vs ``c``), so a new key can never
# equal a legacy name-based key whatever the device names are. The shared base
# URL key ``esphome_ota_base_url`` is disjoint from both for the same reason.
SLUG_SECRET_PREFIX = "esphome_ota_cfg_"
LEGACY_SLUG_SECRET_PREFIX = "esphome_ota_slug_"
# One key shared by every device: base_url is global to the config entry.
BASE_URL_SECRET_KEY = "esphome_ota_base_url"
_SECRET_KEY_BAD_RE = re.compile(r"[^a-z0-9_]")


def normalize_base_url(value: str) -> str | None:
    """Return the cleaned base URL, or None when it is not a valid http(s) URL."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip("/")
    try:
        parsed = urlsplit(cleaned)
        parsed.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if (
        parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or any(ch.isspace() for ch in cleaned)
    ):
        return None
    return cleaned


BASE_URL_INVALID_MESSAGE = (
    "The Base URL is empty or not a valid http(s) URL, so the OTA secrets "
    "cannot be stored. Nothing was written. Set a valid Base URL in the "
    "ESPHome OTA integration options (Settings > Devices & services > "
    "ESPHome OTA > Configure), then try again."
)


def slug_secret_key(device_id: str) -> str:
    """Return the ``secrets.yaml`` key holding the public slug of a device.

    Derived from the device id (the configuration file stem), which is unique
    within one Builder config directory. ``esphome.name`` is NOT unique, so
    two files sharing a name would otherwise overwrite each other's slug. The
    id is lowercased and mapped to ``[a-z0-9_]``; when that mapping is lossy
    (e.g. ``-`` -> ``_``) a short hash of the original id is appended so
    ``a-b`` and ``a_b`` never share a key.
    """
    clean = _SECRET_KEY_BAD_RE.sub("_", device_id.lower())
    if clean != device_id:
        digest = hashlib.sha1(device_id.encode("utf-8")).hexdigest()[:6]
        clean = f"{clean}_{digest}"
    return f"{SLUG_SECRET_PREFIX}{clean}"


def legacy_slug_secret_key(node: str) -> str:
    """Return the name-based key that 1.7.0b0/b1 used (``esphome.name`` based)."""
    clean = _SECRET_KEY_BAD_RE.sub("_", node.lower())
    if clean != node:
        digest = hashlib.sha1(node.encode("utf-8")).hexdigest()[:6]
        clean = f"{clean}_{digest}"
    return f"{LEGACY_SLUG_SECRET_PREFIX}{clean}"


def find_slug_key_conflict(
    device_id: str,
    other_ids: Iterable[str],
    other_names: Iterable[str] = (),
) -> str | None:
    """Return another device id/name whose slug key equals this device's key.

    ``other_ids`` are compared with the current key scheme; ``other_names`` are
    ``esphome.name`` values compared with the legacy name-based key (defense in
    depth: the prefixes are disjoint, so this can only trigger if that ever
    changes).
    """
    key = slug_secret_key(device_id)
    for other in other_ids:
        if other != device_id and slug_secret_key(other) == key:
            return other
    for name in other_names:
        if legacy_slug_secret_key(name) == key:
            return name
    return None


def project_name(node: str) -> str:
    """Return 'local.<node>' capped at ESPHome's 32-character project.name limit."""
    name = f"local.{node}"
    return name if len(name) <= _PROJECT_NAME_MAX else name[:_PROJECT_NAME_MAX]


HEADER = """\
# ---------------------------------------------------------------------------
# Generated by ESPHome OTA. Managed automatically.
# ---------------------------------------------------------------------------
"""


def generate_inline_ota_yaml(
    base_url: str,
    slug: str,
    version: str | None = None,
    publish_dir: str = DEFAULT_PUBLISH_DIR,
    node: str = "",
    use_project: bool = True,
    slug_secret: str | None = None,
    base_url_secret: str | None = None,
) -> str:
    """Generate YAML snippet for packages.esphome_ota.

    With ``slug_secret`` the slug is emitted as ``!secret <key>`` so the device
    YAML never contains the public-URL token; otherwise it is inlined. The same
    applies to ``base_url_secret`` and ``ota_base_url`` (the private HA URL).
    """
    slug_value = f"!secret {slug_secret}" if slug_secret else yaml_dq(slug)
    clean_base_url = base_url.rstrip("/")
    base_url_value = (
        f"!secret {base_url_secret}" if base_url_secret else yaml_dq(clean_base_url)
    )
    proj_block = ""
    if use_project and node and version:
        proj_block = f"""    esphome:
      project:
        name: {yaml_dq(project_name(node))}
        version: {yaml_dq(version)}\n"""

    return f"""\
  esphome_ota:
    substitutions:
      ota_base_url: {base_url_value}
      ota_slug: {slug_value}
{proj_block}    http_request:
      timeout: 60s

    ota:
      - platform: http_request
        id: ota_http

    safe_mode:

    update:
      - platform: http_request
        id: ota_update
        ota_id: ota_http
        name: "Firmware"
        source: "${{ota_base_url}}/local/{publish_dir}/${{ota_slug}}.json"
        update_interval: 6h
"""
