"""Secret redaction helpers for runtime logs and public proof surfaces."""

from __future__ import annotations

import re
from typing import Any


_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|credential)\s*([:=])\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(authorization\s*:\s*bearer|bearer)\s+([^\s,;]+)")
_COMMON_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9][A-Za-z0-9._-]{8,})\b")


def redact_text(value: Any) -> str:
    """Return text with common secret-like values replaced."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = _ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _BEARER_RE.sub(lambda match: f"{match.group(1)} [REDACTED]", text)
    return _COMMON_KEY_RE.sub("[REDACTED]", text)


def redact_data(value: Any) -> Any:
    """Recursively redact secret-like strings from simple JSON-compatible data."""
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
