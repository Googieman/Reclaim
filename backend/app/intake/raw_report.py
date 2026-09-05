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


def report_capture_payload(
    *,
    report_content: str | None,
    report_reference: str | None,
    incident_type: str | None = None,
    occurred_at: str | None = None,
    narrative: str | None = None,
    customer_reference: str | None = None,
    account_reference: str | None = None,
    order_reference: str | None = None,
    payment_reference: str | None = None,
    reported_amount_minor: int | None = None,
    reported_currency: str | None = None,
    external_reference: str | None = None,
) -> bytes:
    """Capture the raw report and typed intake metadata immutably.

    The returned bytes are written only to MinIO.  They are never copied into
    Redpanda payloads or ordinary application logs.
    """

    return json.dumps(
        {
            "report_content": report_content,
            "report_reference": report_reference,
            "incident_type": incident_type,
            "occurred_at": occurred_at,
            "narrative": narrative,
            "customer_reference": customer_reference,
            "account_reference": account_reference,
            "order_reference": order_reference,
            "payment_reference": payment_reference,
            "reported_amount_minor": reported_amount_minor,
            "reported_currency": reported_currency,
            "external_reference": external_reference,
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
