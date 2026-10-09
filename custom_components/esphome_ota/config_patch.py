"""YAML patch generation, version ownership analysis, and CAS modification."""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

import yaml

from .models import YamlDiff
from .packages import generate_inline_ota_yaml

_LOGGER = logging.getLogger(__name__)


class _SafeEsphomeLoader(yaml.SafeLoader):
    """YAML SafeLoader tolerating ESPHome custom tags like !secret, !include, !lambda."""


def _unknown_tag(loader: yaml.Loader, suffix: str, node: yaml.Node) -> Any:
    if suffix == "include":
        if isinstance(node, yaml.ScalarNode):
            return {"__include__": loader.construct_scalar(node)}
        if isinstance(node, yaml.MappingNode):
            mapping = loader.construct_mapping(node, deep=True)
            return {"__include__": str(mapping.get("file", ""))}
    return None


_SafeEsphomeLoader.add_multi_constructor("!", _unknown_tag)


def parse_yaml_safe(content: str) -> dict[str, Any]:
    """Parse YAML content safely tolerating ESPHome custom tags."""
    try:
        data = yaml.load(content, Loader=_SafeEsphomeLoader)  # noqa: S506
        return data if isinstance(data, dict) else {}
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Safe YAML parse warning: %s", err)
        return {}


def own_project_version(content: str) -> str | None:
    """Detect if device YAML owns its own esphome.project.version.

    Returns the version string if user owns it, else None.
    Carefully distinguishes esphome.project.version from esp32.framework.version.
    Resolves substitutions if defined locally in the configuration.
    """
    data = parse_yaml_safe(content)
    esphome_block = data.get("esphome")
    if isinstance(esphome_block, dict):
        project_block = esphome_block.get("project")
        if isinstance(project_block, dict):
            version = project_block.get("version")
            if version is not None:
                ver_str = str(version).strip()
                # Resolve local substitution if present
                substitutions = data.get("substitutions")
                if isinstance(substitutions, dict):
                    if ver_str.startswith("${") and ver_str.endswith("}"):
                        key = ver_str[2:-1].strip()
                        if key in substitutions:
                            return str(substitutions[key]).strip()
                    elif ver_str.startswith("$"):
                        key = ver_str[1:].strip()
                        if key in substitutions:
                            return str(substitutions[key]).strip()
                return ver_str

    # Also detect if external packages define project version
    packages = data.get("packages")
    if isinstance(packages, dict):
        for pkg_name, pkg_val in packages.items():
            if pkg_name == "esphome_ota":
                continue
            if isinstance(pkg_val, dict):
                p_ver = pkg_val.get("esphome", {}).get("project", {}).get("version")
                if p_ver is not None:
                    return str(p_ver).strip()
    return None


def has_unclear_project_ownership(content: str) -> bool:
    """Check if project ownership is ambiguous due to included packages/esphome configs or unresolved substitutions."""
    data = parse_yaml_safe(content)

    # 1. Check if esphome block itself is an include or contains an include or unresolved substitution
    esphome_block = data.get("esphome")
    if isinstance(esphome_block, dict):
        if "__include__" in esphome_block:
            return True
        project_block = esphome_block.get("project")
        if isinstance(project_block, dict):
            if "__include__" in project_block:
                return True
            ver = project_block.get("version")
            if ver is not None:
                ver_str = str(ver).strip()
                # Check for unresolved substitution
                resolved = own_project_version(content)
                if ("$" in ver_str or "{" in ver_str) and (not resolved or "$" in resolved or "{" in resolved):
                    return True
    elif esphome_block == {"__include__": ...} or (
        isinstance(content, str) and bool(re.search(r"^\s*esphome:\s*!include", content, re.MULTILINE))
    ):
        return True

    # 2. Check if packages block uses includes that might contain project definitions
    packages = data.get("packages")
    if isinstance(packages, dict):
        for pkg_name, pkg_val in packages.items():
            if pkg_name == "esphome_ota":
                continue
            if isinstance(pkg_val, dict) and "__include__" in pkg_val:
                return True
    elif isinstance(content, str) and bool(re.search(r"^\s*packages:\s*!include", content, re.MULTILINE)):
        return True

    return False


def bump_patch_version(version: str) -> str:
    """Increment the patch component of a semantic version string (e.g. 1.0.0 -> 1.0.1)."""
    parts = version.strip().split(".")
    if len(parts) >= 3 and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    if len(parts) == 2 and parts[-1].isdigit():
        return f"{parts[0]}.{parts[1]}.1"
    if len(parts) == 1 and parts[0].isdigit():
        return f"{parts[0]}.0.1"
    return f"{version}.1"


def apply_ota_patch(
    yaml_content: str,
    base_url: str,
    slug: str,
    target_version: str | None = None,
    node: str = "",
) -> YamlDiff:
    """Apply the managed packages.esphome_ota block into YAML while preserving comments and format."""
    original = yaml_content
    own_ver = own_project_version(original)
    unclear = has_unclear_project_ownership(original)
    use_project = (own_ver is None) and not unclear

    patch_yaml = generate_inline_ota_yaml(
        base_url=base_url,
        slug=slug,
        version=target_version if use_project else None,
        node=node,
        use_project=use_project,
    )

    lines = original.splitlines(keepends=True)
    new_lines: list[str] = []

    # Check if packages: block already exists
    has_packages = any(re.match(r"^packages\s*:", line) for line in lines)
    in_managed_block = False

    if has_packages:
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r"^packages\s*:", line):
                new_lines.append(line)
                i += 1
                # Insert the new managed block immediately under packages:
                new_lines.append(patch_yaml)
                # Skip any existing esphome_ota block
                while i < len(lines):
                    sub_line = lines[i]
                    if re.match(r"^  esphome_ota\s*:", sub_line):
                        in_managed_block = True
                        i += 1
                        continue
                    if in_managed_block:
                        # Inside existing esphome_ota block (indented by >= 4 spaces or blank)
                        if sub_line.strip() == "" or re.match(r"^    ", sub_line):
                            i += 1
                            continue
                        in_managed_block = False
                    new_lines.append(sub_line)
                    i += 1
                break
            new_lines.append(line)
            i += 1
    else:
        # Append packages: block at the end
        new_lines = list(lines)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append("\npackages:\n")
        new_lines.append(patch_yaml)

    modified = "".join(new_lines)
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile="original.yaml",
            tofile="modified.yaml",
        )
    )

    return YamlDiff(
        original=original,
        modified=modified,
        diff=diff,
        mode="inline_package",
        will_change_ownership=False,
        previous_version=own_ver,
        target_version=target_version,
    )


def remove_ota_patch(yaml_content: str) -> tuple[str, bool]:
    """Remove managed packages.esphome_ota block from YAML while preserving the rest."""
    lines = yaml_content.splitlines(keepends=True)
    new_lines: list[str] = []
    in_managed_block = False
    removed = False

    for line in lines:
        if re.match(r"^  esphome_ota\s*:", line):
            in_managed_block = True
            removed = True
            continue
        if in_managed_block:
            if line.strip() == "" or re.match(r"^    ", line):
                continue
            in_managed_block = False
        new_lines.append(line)

    return "".join(new_lines), removed
