"""Scrub the secret public-URL token from log output."""

from __future__ import annotations

import logging
import re
import traceback

_TOKEN_HEX_RE = re.compile(r"_[0-9a-f]{32}(?![0-9a-f])")
# Public files are named ``{name}_{token}.json`` / ``.ota.bin`` / ``.ota.bin.md5``.
_PUBLIC_FILE_RE = re.compile(
    r"_[^\s/\\'\"_]+(?=\.(?:ota\.bin\.md5|ota\.bin|ota\.json|json)\b)"
)


def mask_slug(slug: str) -> str:
    """Hide the secret token of a public slug (``{name}_{token}``)."""
    if "_" not in slug:
        return slug
    return slug.rsplit("_", 1)[0] + "_***"


def redact(text: str) -> str:
    """Replace URL tokens embedded in file names or slugs inside ``text``."""
    return _PUBLIC_FILE_RE.sub("_***", _TOKEN_HEX_RE.sub("_***", text))


class _RedactionFilter(logging.Filter):
    """Redact the formatted message and traceback of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        record.msg = redact(message)
        record.args = None
        if record.exc_info:
            record.exc_text = redact(
                "".join(traceback.format_exception(*record.exc_info))
            )
            record.exc_info = None
        return True


def install_redaction(logger: logging.Logger) -> None:
    """Attach the redaction filter to ``logger`` once."""
    if not any(isinstance(f, _RedactionFilter) for f in logger.filters):
        logger.addFilter(_RedactionFilter())
