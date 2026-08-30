"""Immutable object references for submitted incident report provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from packages.contracts.common import Reference


class RawReportObject(Protocol):
    """Minimum immutable-store result needed to create a durable reference."""

    object_name: str
    checksum: str


class RawReportStore(Protocol):
    """Approved immutable object store used by incident intake."""

    def put(
        self,
        *,
        tenant_id: str,
        object_name: str,
        content: bytes,
        content_type: str,
        expected_checksum: str,
    ) -> RawReportObject: ...


@dataclass(frozen=True, slots=True)
class RawReportReference:
    """Serializable reference to the immutable report capture and its digest."""

    reference_id: str
    checksum: str

    def serialized(self) -> str:
        payload = Reference(
            reference_id=self.reference_id,
            reference_type="incident.report.raw",
            checksum=self.checksum,
        ).model_dump()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def report_capture_payload(*, report_content: str | None, report_reference: str | None) -> bytes:
    """Capture both inline content and an optional external pointer without logging either."""

    return json.dumps(
        {
            "report_content": report_content,
            "report_reference": report_reference,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def report_object_name(*, tenant_id: str, idempotency_key: str) -> str:
    """Return a stable, non-sensitive object name for retry-safe report capture."""

    identity = f"{tenant_id}|{idempotency_key}".encode()
    digest = hashlib.sha256(identity).hexdigest()
    return f"incidents/raw-reports/{digest}.json"


__all__ = [
    "RawReportObject",
    "RawReportReference",
    "RawReportStore",
    "report_capture_payload",
    "report_object_name",
]
