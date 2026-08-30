"""Recursive telemetry/model-input redaction for untrusted and sensitive data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = frozenset(
    {
        "secret",
        "token",
        "password",
        "authorization",
        "cookie",
        "private_key",
        "api_key",
        "raw_payload",
        "email",
        "phone",
        "address",
        "full_name",
    }
)


def redact(value: Any) -> Any:
    """Return JSON-like data with secrets and unnecessary PII removed."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)
