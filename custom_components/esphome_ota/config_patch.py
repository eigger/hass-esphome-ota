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
        data = yaml.load(content, Loader=_SafeEsphomeLoader)
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


def _is_external_or_include_package(pkg_val: Any) -> bool:
    """Check if a package entry references an external package or include."""
    if isinstance(pkg_val, str):
        val_lower = pkg_val.strip().lower()
        if any(val_lower.startswith(prefix) for prefix in ("github://", "http://", "https://", "git://", "ssh://")):
            return True
        if "!include" in val_lower:
            return True
    elif isinstance(pkg_val, dict):
        if "__include__" in pkg_val:
            return True
        if any(k in pkg_val for k in ("url", "files", "file", "repo")):
            return True
    return False


def has_unclear_project_ownership(content: str) -> bool:
    """Check if project ownership is ambiguous due to included packages/esphome configs or unresolved substitutions.

    Top-level explicit project.version takes precedence and clarifies ownership.
    Remote packages (github://, url/files) or included packages without top-level version
    are considered ambiguous.
    """
    data = parse_yaml_safe(content)

    # 1. Top-level explicit project version has precedence!
    esphome_block = data.get("esphome")
    top_level_project_ver: str | None = None
    if isinstance(esphome_block, dict) and "__include__" not in esphome_block:
        project_block = esphome_block.get("project")
        if isinstance(project_block, dict) and "__include__" not in project_block:
            ver = project_block.get("version")
            if ver is not None:
                ver_str = str(ver).strip()
                if "$" not in ver_str and "{" not in ver_str:
                    top_level_project_ver = ver_str
                else:
                    resolved = own_project_version(content)
                    if resolved and "$" not in resolved and "{" not in resolved:
                        top_level_project_ver = resolved

    if top_level_project_ver is not None:
        # User explicitly and concretely defines project version at top-level.
        # This overrides any packages (!include or remote github/url).
        return False

    # 2. Check if esphome block itself is an include or contains an include or unresolved substitution
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
                resolved = own_project_version(content)
                if ("$" in ver_str or "{" in ver_str) and (not resolved or "$" in resolved or "{" in resolved):
                    return True
    elif esphome_block == {"__include__": ...} or (
        isinstance(content, str) and bool(re.search(r"^\s*esphome:\s*!include", content, re.MULTILINE))
    ):
        return True

    # 3. Check if packages block uses includes or remote packages (github://, url/files)
    packages = data.get("packages")
    if isinstance(packages, dict):
        for pkg_name, pkg_val in packages.items():
            if pkg_name == "esphome_ota":
                continue
            if _is_external_or_include_package(pkg_val):
                return True
    elif isinstance(packages, list):
        for pkg_val in packages:
            if _is_external_or_include_package(pkg_val):
                return True
    elif isinstance(content, str) and bool(re.search(r"^\s*packages:\s*!include", content, re.MULTILINE)):
        return True

    # Check raw content for remote github packages
    return bool(
        isinstance(content, str)
        and (
            re.search(r"github://", content)
            or re.search(r"^\s*-\s*github://", content, re.MULTILINE)
        )
    )


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


def reindent_yaml_snippet(snippet: str, indent_size: int = 2) -> str:
    """Adjust snippet indentation based on detected indent size (e.g. 2 or 4 spaces)."""
    if indent_size == 2:
        return snippet
    new_snippet_lines = []
    in_seq_map = False
    seq_col = 0
    for line in snippet.splitlines(keepends=True):
        if not line.strip():
            new_snippet_lines.append(line)
            continue
        stripped = line.lstrip(" ")
        leading_spaces = len(line) - len(stripped)
        if stripped.startswith("- "):
            level = leading_spaces // 2
            new_leading = " " * (level * indent_size)
            seq_col = len(new_leading) + 2
            in_seq_map = True
            new_snippet_lines.append(new_leading + stripped)
        elif in_seq_map and leading_spaces == 8:
            new_snippet_lines.append(" " * seq_col + stripped)
        else:
            in_seq_map = False
            level = leading_spaces // 2
            new_leading = " " * (level * indent_size)
            new_snippet_lines.append(new_leading + stripped)
    return "".join(new_snippet_lines)


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

    # Detect direct child package indentation under packages:
    base_indent = 2
    has_existing_ota = False
    if has_packages:
        in_pkg = False
        for line in lines:
            if re.match(r"^packages\s*:", line):
                in_pkg = True
                continue
            if in_pkg:
                if not line.strip() or line.strip().startswith("#"):
                    continue
                if not line.startswith(" "):
                    break
                stripped = line.lstrip(" ")
                base_indent = len(line) - len(stripped)
                break

        in_pkg = False
        for line in lines:
            if re.match(r"^packages\s*:", line):
                in_pkg = True
                continue
            if in_pkg:
                if not line.strip() or line.strip().startswith("#"):
                    continue
                if not line.startswith(" "):
                    break
                stripped = line.lstrip(" ")
                cur_indent = len(line) - len(stripped)
                if cur_indent == base_indent and re.match(r"^esphome_ota\s*:", stripped):
                    has_existing_ota = True
                    break

    patch_yaml = reindent_yaml_snippet(patch_yaml, indent_size=base_indent)

    if has_packages:
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r"^packages\s*:", line):
                new_lines.append(line)
                i += 1
                if not has_existing_ota:
                    # Insert the new managed block immediately under packages:
                    new_lines.append(patch_yaml)

                in_managed_block = False
                block_indent = base_indent
                while i < len(lines):
                    sub_line = lines[i]
                    # Check if exiting packages block (unindented non-empty, non-comment line)
                    if sub_line.strip() and not sub_line.startswith(" ") and not sub_line.strip().startswith("#"):
                        break

                    m_ota = re.match(r"^(\s+)esphome_ota\s*:", sub_line)
                    if m_ota and len(m_ota.group(1)) == base_indent:
                        in_managed_block = True
                        block_indent = len(m_ota.group(1))
                        # Replace in place!
                        new_lines.append(patch_yaml)
                        i += 1
                        continue

                    if in_managed_block:
                        if sub_line.strip() == "":
                            i += 1
                            continue
                        sub_indent = len(sub_line) - len(sub_line.lstrip(" "))
                        if sub_indent > block_indent:
                            i += 1
                            continue
                        if sub_line.strip().startswith("#") and sub_indent >= block_indent:
                            i += 1
                            continue
                        in_managed_block = False

                    new_lines.append(sub_line)
                    i += 1
                continue
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
