"""Byte-size enforcement shared by intake, connectors, and raw storage."""

from __future__ import annotations


class PayloadLimitError(ValueError):
    """Raised without including untrusted payload content in the error."""


def enforce_payload_limit(payload: bytes, *, max_bytes: int, label: str) -> None:
    """Reject a non-byte or oversized payload with a stable, redacted message."""

    if not isinstance(payload, bytes):
        raise TypeError(f"{label} payload must be bytes")
    if max_bytes < 1:
        raise ValueError(f"{label} payload limit must be positive")
    if len(payload) > max_bytes:
        raise PayloadLimitError(f"{label} payload exceeds configured size limit")


def utf8_size(value: str, *, label: str, max_bytes: int) -> None:
    """Enforce a UTF-8 byte limit on a structured text field."""

    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    enforce_payload_limit(value.encode("utf-8"), max_bytes=max_bytes, label=label)


__all__ = ["PayloadLimitError", "enforce_payload_limit", "utf8_size"]
