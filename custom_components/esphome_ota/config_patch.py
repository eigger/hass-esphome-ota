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


def is_legacy_ota_server_package(pkg_val: Any) -> bool:
    """Check if a package entry references the legacy ota_server package/wrapper."""
    if isinstance(pkg_val, str):
        val_lower = pkg_val.strip().lower()
        return "ota_server" in val_lower
    if isinstance(pkg_val, dict):
        inc = pkg_val.get("__include__")
        if isinstance(inc, str) and "ota_server" in inc.lower():
            return True
        url = pkg_val.get("url") or ""
        files = str(pkg_val.get("files") or pkg_val.get("file") or "")
        if "ota_server" in str(url).lower() or "ota_server" in files.lower():
            return True
    return False


def _strip_yaml_comment(line: str) -> str:
    """Strip comment from a YAML line while respecting basic quotes."""
    in_quote: str | None = None
    escaped = False
    for i, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in ('"', "'"):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
            continue
        if ch == "#" and in_quote is None:
            return line[:i].rstrip()
    return line.rstrip("\r\n")


def strip_legacy_ota_packages(yaml_content: str) -> tuple[str, bool]:
    """Strip legacy ota_server package includes and legacy substitutions from YAML text.

    Returns (new_content, changed).
    """
    if "ota_server" not in yaml_content and "ota_device:" not in yaml_content and "ota_slug:" not in yaml_content:
        return yaml_content, False

    lines = yaml_content.splitlines(keepends=True)
    changed = False

    def _indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" \t"))

    def _is_top_level(line: str) -> bool:
        return bool(
            line.strip()
            and not line.startswith((" ", "\t"))
            and not line.lstrip().startswith("#")
        )

    # 1. Clean legacy substitutions: ota_device and ota_slug
    sub_idx: int | None = None
    for idx, line in enumerate(lines):
        if re.match(r"^substitutions\s*:", line):
            sub_idx = idx
            break

    if sub_idx is not None:
        sub_base_indent = 2
        for sub_line in lines[sub_idx + 1 :]:
            if not sub_line.strip() or sub_line.lstrip().startswith("#"):
                continue
            if _is_top_level(sub_line):
                break
            sub_base_indent = _indent_of(sub_line)
            break

        new_lines: list[str] = list(lines[: sub_idx + 1])
        sub_rem_count = 0
        sub_changed = False
        i = sub_idx + 1
        after_sub_idx = len(lines)
        while i < len(lines):
            line = lines[i]
            if _is_top_level(line):
                after_sub_idx = i
                break
            if not line.strip() or line.lstrip().startswith("#"):
                new_lines.append(line)
                i += 1
                continue
            ind = _indent_of(line)
            line_code = _strip_yaml_comment(line)
            if ind == sub_base_indent and re.match(r"^[ \t]+(ota_device|ota_slug)\s*:", line_code):
                sub_changed = True
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if _is_top_level(nxt):
                        break
                    if not nxt.strip():
                        i += 1
                        continue
                    if _indent_of(nxt) > sub_base_indent:
                        i += 1
                        continue
                    break
                continue
            if ind == sub_base_indent:
                sub_rem_count += 1
            new_lines.append(line)
            i += 1
        after_sub_idx = i

        if sub_changed:
            changed = True
            if sub_rem_count == 0:
                before = lines[:sub_idx]
                while before and not before[-1].strip():
                    before.pop()
                after = lines[after_sub_idx:]
                lines = before + (["\n"] if before and after else []) + after
            else:
                lines = new_lines + lines[after_sub_idx:]

    # 2. Clean packages: block of ota_server entries
    packages_idx: int | None = None
    for idx, line in enumerate(lines):
        if re.match(r"^packages\s*:", line):
            packages_idx = idx
            break

    if packages_idx is not None:
        pkg_line = lines[packages_idx]
        pkg_code = _strip_yaml_comment(pkg_line).strip()
        # Only drop the packages: line itself if it is a standalone !include to ota_server
        if re.match(r"^packages\s*:\s*!include\b", pkg_code) and "ota_server" in pkg_code.lower():
            lines.pop(packages_idx)
            changed = True
        else:
            pkg_base_indent = 2
            for sub_line in lines[packages_idx + 1 :]:
                if not sub_line.strip() or sub_line.lstrip().startswith("#"):
                    continue
                if _is_top_level(sub_line):
                    break
                pkg_base_indent = _indent_of(sub_line)
                break

            before_pkg = lines[:packages_idx]
            kept_pkg_children: list[str] = []
            pkg_rem_count = 0
            pkg_changed = False

            i = packages_idx + 1
            after_pkg_idx = len(lines)
            while i < len(lines):
                line = lines[i]
                if _is_top_level(line):
                    after_pkg_idx = i
                    break
                if not line.strip() or line.lstrip().startswith("#"):
                    kept_pkg_children.append(line)
                    i += 1
                    continue
                ind = _indent_of(line)
                if ind == pkg_base_indent:
                    entry_lines = [line]
                    j = i + 1
                    while j < len(lines):
                        nxt = lines[j]
                        if _is_top_level(nxt):
                            break
                        if not nxt.strip():
                            j += 1
                            continue
                        if _indent_of(nxt) > pkg_base_indent:
                            entry_lines.append(nxt)
                            j += 1
                            continue
                        if nxt.lstrip().startswith("#") and _indent_of(nxt) >= pkg_base_indent:
                            entry_lines.append(nxt)
                            j += 1
                            continue
                        break
                    # Check code portion only, ignoring comments
                    code_lines = [_strip_yaml_comment(entry_line) for entry_line in entry_lines]
                    code_str = "\n".join(code_lines).lower()
                    if "ota_server" in code_str:
                        pkg_changed = True
                        i = j
                        continue
                    else:
                        pkg_rem_count += 1
                        kept_pkg_children.extend(entry_lines)
                        i = j
                        continue
                kept_pkg_children.append(line)
                i += 1
            after_pkg_idx = i

            if pkg_changed:
                changed = True
                after_pkg = lines[after_pkg_idx:]
                if pkg_rem_count == 0:
                    while before_pkg and not before_pkg[-1].strip():
                        before_pkg.pop()
                    if before_pkg and not before_pkg[-1].endswith("\n"):
                        before_pkg[-1] += "\n"
                    lines = before_pkg + after_pkg
                else:
                    while kept_pkg_children and not kept_pkg_children[0].strip():
                        kept_pkg_children.pop(0)
                    while kept_pkg_children and not kept_pkg_children[-1].strip():
                        kept_pkg_children.pop()
                    header = lines[packages_idx]
                    if not header.endswith("\n"):
                        header += "\n"
                    body = before_pkg + [header] + kept_pkg_children
                    if kept_pkg_children and not kept_pkg_children[-1].endswith("\n") and after_pkg:
                        body[-1] += "\n"
                    lines = body + after_pkg

    if not changed:
        return yaml_content, False

    result = "".join(lines)
    return re.sub(r"\n{3,}", "\n\n", result), True


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
    are considered ambiguous. Legacy ota_server packages are not ambiguous as they will be replaced.
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
            if is_legacy_ota_server_package(pkg_val):
                continue
            if _is_external_or_include_package(pkg_val):
                return True
    elif isinstance(packages, list):
        for pkg_val in packages:
            if is_legacy_ota_server_package(pkg_val):
                continue
            if _is_external_or_include_package(pkg_val):
                return True
    elif isinstance(content, str):
        match_pkg_inc = re.search(r"^\s*packages:\s*!include\s+(.*)$", content, re.MULTILINE)
        if match_pkg_inc:
            target = _strip_yaml_comment(match_pkg_inc.group(1)).lower()
            if "ota_server" not in target:
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


def _format_yaml_scalar(value: str) -> str:
    """Quote a scalar when needed for safe YAML round-trip."""
    if value == "":
        return '""'
    if re.fullmatch(r"[0-9]+(\.[0-9]+)*", value):
        return f'"{value}"'
    if re.search(r'[:#\[\]{},&*?|>!%@`\'"\s]', value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def set_project_version(content: str, new_version: str) -> tuple[str, bool]:
    """Update top-level esphome.project.version (or its local substitution) in YAML text.

    Prefers editing the local substitution target when version uses ``${key}`` / ``$key``.
    Returns (new_content, changed).
    """
    new_version = str(new_version).strip()
    if not new_version:
        return content, False

    data = parse_yaml_safe(content)
    esphome_block = data.get("esphome")
    if not isinstance(esphome_block, dict) or "__include__" in esphome_block:
        return content, False
    project_block = esphome_block.get("project")
    if not isinstance(project_block, dict) or "__include__" in project_block:
        return content, False
    current = project_block.get("version")
    if current is None:
        return content, False

    current_str = str(current).strip()
    sub_key: str | None = None
    if current_str.startswith("${") and current_str.endswith("}"):
        sub_key = current_str[2:-1].strip()
    elif current_str.startswith("$") and not current_str.startswith("${"):
        sub_key = current_str[1:].strip()

    lines = content.splitlines(keepends=True)
    formatted = _format_yaml_scalar(new_version)
    changed = False

    if sub_key:
        substitutions = data.get("substitutions")
        if not isinstance(substitutions, dict) or sub_key not in substitutions:
            # Replace the version reference itself with a concrete literal.
            sub_key = None
        else:
            in_subs = False
            for idx, line in enumerate(lines):
                if re.match(r"^substitutions\s*:", line):
                    in_subs = True
                    continue
                if in_subs:
                    if line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                        break
                    match = re.match(
                        rf"^(\s+){re.escape(sub_key)}\s*:\s*.*(\r?\n)?$",
                        line,
                    )
                    if match:
                        indent = match.group(1)
                        nl = "\n" if line.endswith("\n") else ""
                        if line.endswith("\r\n"):
                            nl = "\r\n"
                        lines[idx] = f"{indent}{sub_key}: {formatted}{nl}"
                        changed = True
                        break
            if changed:
                return "".join(lines), True
            return content, False

    # Walk esphome -> project -> version with indentation awareness
    in_esphome = False
    in_project = False
    esphome_indent: int | None = None
    project_indent: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.lstrip(" ")
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        indent = len(line) - len(stripped)

        if re.match(r"^esphome\s*:", line):
            in_esphome = True
            in_project = False
            esphome_indent = indent
            project_indent = None
            continue

        if in_esphome:
            if indent <= (esphome_indent or 0) and re.match(r"^\S", stripped):
                in_esphome = False
                in_project = False
            elif re.match(r"^project\s*:", stripped) and indent > (esphome_indent or 0):
                in_project = True
                project_indent = indent
                continue
            elif in_project:
                if indent <= (project_indent or 0):
                    in_project = False
                elif re.match(r"^version\s*:", stripped):
                    nl = "\n"
                    if line.endswith("\r\n"):
                        nl = "\r\n"
                    elif line.endswith("\n"):
                        nl = "\n"
                    else:
                        nl = ""
                    lines[idx] = f"{' ' * indent}version: {formatted}{nl}"
                    changed = True
                    break

    if not changed:
        return content, False
    return "".join(lines), True


def ensure_project_version(
    content: str,
    new_version: str,
    project_name: str = "esphome_ota.device",
) -> tuple[str, bool]:
    """Ensure top-level ``esphome.project.version`` is set to ``new_version``.

    Updates an existing version (or its local substitution). If ``project`` /
    ``version`` is missing under a concrete ``esphome:`` mapping, inserts them.
    Returns (new_content, changed).
    """
    new_version = str(new_version).strip()
    if not new_version:
        return content, False

    updated, changed = set_project_version(content, new_version)
    if changed:
        return updated, True

    data = parse_yaml_safe(content)
    esphome_block = data.get("esphome")
    if not isinstance(esphome_block, dict) or "__include__" in esphome_block:
        return content, False
    if isinstance(content, str) and re.search(
        r"^\s*esphome:\s*!include", content, re.MULTILINE
    ):
        return content, False

    formatted = _format_yaml_scalar(new_version)
    name_formatted = _format_yaml_scalar(project_name)
    lines = content.splitlines(keepends=True)

    esphome_idx: int | None = None
    esphome_indent = 0
    project_idx: int | None = None
    project_indent: int | None = None
    child_indent: int | None = None

    for idx, line in enumerate(lines):
        stripped = line.lstrip(" ")
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if re.match(r"^esphome\s*:", line):
            esphome_idx = idx
            esphome_indent = indent
            continue
        if esphome_idx is None:
            continue
        if indent <= esphome_indent and re.match(r"^\S", stripped):
            break
        if child_indent is None and indent > esphome_indent:
            child_indent = indent
        if re.match(r"^project\s*:", stripped) and indent > esphome_indent:
            project_idx = idx
            project_indent = indent
            break

    if esphome_idx is None:
        return content, False

    child_indent = child_indent if child_indent is not None else esphome_indent + 2
    nl = "\n"
    if lines[esphome_idx].endswith("\r\n"):
        nl = "\r\n"

    if project_idx is not None and project_indent is not None:
        # Insert version as first child of existing project: block
        insert_at = project_idx + 1
        version_indent = project_indent + (child_indent - esphome_indent)
        # Prefer indent of existing project children when present
        for sub in lines[project_idx + 1 :]:
            if not sub.strip() or sub.lstrip().startswith("#"):
                continue
            sub_indent = len(sub) - len(sub.lstrip(" "))
            if sub_indent > project_indent:
                version_indent = sub_indent
            break
        lines.insert(
            insert_at,
            f"{' ' * version_indent}version: {formatted}{nl}",
        )
        return "".join(lines), True

    # Insert a full project block under esphome:
    insert_at = esphome_idx + 1
    block = (
        f"{' ' * child_indent}project:{nl}"
        f"{' ' * (child_indent + (child_indent - esphome_indent))}name: {name_formatted}{nl}"
        f"{' ' * (child_indent + (child_indent - esphome_indent))}version: {formatted}{nl}"
    )
    lines.insert(insert_at, block)
    return "".join(lines), True


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

    # Strip legacy ota_server packages and substitutions first
    clean_yaml, _ = strip_legacy_ota_packages(yaml_content)

    # Derive node fallback if missing
    if not node:
        parsed = parse_yaml_safe(clean_yaml)
        esphome_block = parsed.get("esphome")
        if isinstance(esphome_block, dict):
            name_val = esphome_block.get("name")
            if name_val:
                node = str(name_val).strip()
        if not node and slug:
            node = slug.split("_")[0]

    # Derive version fallback if missing
    if not target_version:
        target_version = "1.0.0"

    own_ver = own_project_version(clean_yaml)
    unclear = has_unclear_project_ownership(clean_yaml)
    use_project = (own_ver is None) and not unclear

    patch_yaml = generate_inline_ota_yaml(
        base_url=base_url,
        slug=slug,
        version=target_version if use_project else None,
        node=node,
        use_project=use_project,
    )

    lines = clean_yaml.splitlines(keepends=True)
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
    """Remove managed packages.esphome_ota block from YAML while preserving the rest.

    Detects the indentation used under ``packages:`` (2-space, 4-space, etc.).
    If ``esphome_ota`` was the only package entry, also drops the empty
    ``packages:`` key.
    """
    lines = yaml_content.splitlines(keepends=True)

    packages_idx: int | None = None
    for idx, line in enumerate(lines):
        if re.match(r"^packages\s*:", line):
            packages_idx = idx
            break
    if packages_idx is None:
        return yaml_content, False

    def _indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" \t"))

    def _is_top_level(line: str) -> bool:
        return bool(
            line.strip()
            and not line.startswith((" ", "\t"))
            and not line.lstrip().startswith("#")
        )

    base_indent = 2
    for sub in lines[packages_idx + 1 :]:
        if not sub.strip() or sub.lstrip().startswith("#"):
            continue
        if _is_top_level(sub):
            break
        base_indent = _indent_of(sub)
        break

    before = lines[:packages_idx]
    after_idx = packages_idx + 1
    kept_children: list[str] = []
    removed = False
    remaining_entries = 0

    i = packages_idx + 1
    while i < len(lines):
        line = lines[i]
        if _is_top_level(line):
            after_idx = i
            break

        if not line.strip() or line.lstrip().startswith("#"):
            kept_children.append(line)
            i += 1
            after_idx = i
            continue

        indent = _indent_of(line)
        if indent == base_indent and re.match(r"^[ \t]+esphome_ota\s*:", line):
            removed = True
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if _is_top_level(nxt):
                    break
                if not nxt.strip():
                    i += 1
                    continue
                nxt_indent = _indent_of(nxt)
                if nxt_indent > base_indent:
                    i += 1
                    continue
                if nxt.lstrip().startswith("#") and nxt_indent >= base_indent:
                    i += 1
                    continue
                break
            after_idx = i
            continue

        if indent == base_indent:
            remaining_entries += 1
        kept_children.append(line)
        i += 1
        after_idx = i
    else:
        after_idx = len(lines)

    if not removed:
        return yaml_content, False

    after = lines[after_idx:]
    if remaining_entries == 0:
        while before and not before[-1].strip():
            before.pop()
        if before and not before[-1].endswith("\n"):
            before[-1] += "\n"
        result = "".join(before + after)
        return re.sub(r"\n{3,}", "\n\n", result), True

    while kept_children and not kept_children[0].strip():
        kept_children.pop(0)
    while kept_children and not kept_children[-1].strip():
        kept_children.pop()
    packages_line = lines[packages_idx]
    if not packages_line.endswith("\n"):
        packages_line += "\n"
    body = before + [packages_line] + kept_children
    if kept_children and not kept_children[-1].endswith("\n") and after:
        body[-1] += "\n"
    return "".join(body + after), True
