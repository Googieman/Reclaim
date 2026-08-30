"""Integration coverage for immutable raw evidence and normalized provenance."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
from app.storage.minio_evidence import (
    ImmutableEvidenceStore,
    ObjectIntegrityError,
    checksum_for_bytes,
)

from packages.contracts.connectors import EvidenceResponse

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = ROOT / "tests" / "fixtures" / "evidence" / "session-observation.json"


class MissingObject(Exception):
    code = "NoSuchKey"


@dataclass
class StoredMetadata:
    content: bytes
    checksum: str


class ObjectStat:
    def __init__(self, stored: StoredMetadata) -> None:
        self.size = len(stored.content)
        self.metadata = {"X-Amz-Meta-Sha256": stored.checksum.removeprefix("sha256:")}


class ObjectResponse:
    def __init__(self, stored: StoredMetadata) -> None:
        self.content = stored.content
        self.metadata = {"X-Amz-Meta-Sha256": stored.checksum.removeprefix("sha256:")}

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class MemoryMinio:
    def __init__(self) -> None:
        self.objects: dict[str, StoredMetadata] = {}

    def stat_object(self, bucket_name: str, object_name: str) -> ObjectStat:
        del bucket_name
        try:
            return ObjectStat(self.objects[object_name])
        except KeyError as exc:
            raise MissingObject() from exc

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        length: int,
        **kwargs: object,
    ) -> None:
        del bucket_name, kwargs
        content = data.read()
        assert length == len(content)
        self.objects[object_name] = StoredMetadata(content, checksum_for_bytes(content))

    def get_object(self, bucket_name: str, object_name: str) -> ObjectResponse:
        del bucket_name
        return ObjectResponse(self.objects[object_name])


def test_fixture_raw_object_checksum_and_normalized_provenance_are_linked() -> None:
    raw = EVIDENCE_FIXTURE.read_bytes()
    fixture = json.loads(raw)
    assert fixture["mode"] == "replay"
    assert fixture["seed"] == "us1-evidence-development-001"

    client = MemoryMinio()
    store = ImmutableEvidenceStore(client)
    stored = store.put(
        tenant_id=fixture["tenant_id"],
        object_name=f"{fixture['case_id']}/raw/session-observation.json",
        content=raw,
        expected_checksum=checksum_for_bytes(raw),
        content_type="application/json",
    )
    verified, content = store.get_verified(
        tenant_id=fixture["tenant_id"],
        object_name=f"{fixture['case_id']}/raw/session-observation.json",
    )
    response = EvidenceResponse(
        tenant_id=fixture["tenant_id"],
        correlation_id=fixture["correlation_id"],
        case_id=fixture["case_id"],
        connector_id="sessions-simulator",
        source_identity="merchant-session-store",
        resource_type="sessions",
        observed_at=datetime.fromisoformat(fixture["observed_at"]),
        collected_at=datetime.fromisoformat(fixture["collected_at"]),
        completeness="complete",
        raw_artifact_reference=stored.object_name,
        raw_checksum=stored.checksum,
        normalized_facts=fixture["normalized_facts"],
        connector_status="complete",
    )

    assert content == raw
    assert verified.checksum == checksum_for_bytes(raw)
    assert response.raw_artifact_reference == stored.object_name
    assert response.raw_checksum == verified.checksum
    assert response.normalized_facts[0]["source_event_id"] == "session-event-1"
    assert response.untrusted is True


def test_same_raw_object_is_immutable_and_checksum_mismatch_is_rejected() -> None:
    client = MemoryMinio()
    store = ImmutableEvidenceStore(client)
    object_name = "case-1/raw/evidence.json"
    original = b'{"event":"session.opened"}'
    store.put(tenant_id="tenant-a", object_name=object_name, content=original)

    with pytest.raises(ObjectIntegrityError, match="different content"):
        store.put(tenant_id="tenant-a", object_name=object_name, content=b"tampered")
    with pytest.raises(ObjectIntegrityError, match="does not match content"):
        store.put(
            tenant_id="tenant-a",
            object_name="case-1/raw/other.json",
            content=original,
            expected_checksum="sha256:wrong",
        )


def test_tampered_raw_bytes_fail_verification_against_original_metadata() -> None:
    client = MemoryMinio()
    store = ImmutableEvidenceStore(client)
    key = "tenants/tenant-a/case-1/raw/evidence.json"
    store.put(tenant_id="tenant-a", object_name="case-1/raw/evidence.json", content=b"original")
    client.objects[key].content = b"tampered"

    with pytest.raises(ObjectIntegrityError, match="stored evidence checksum mismatch"):
        store.get_verified(tenant_id="tenant-a", object_name="case-1/raw/evidence.json")


def test_raw_objects_are_separated_by_tenant_prefix() -> None:
    client = MemoryMinio()
    store = ImmutableEvidenceStore(client)
    store.put(tenant_id="tenant-a", object_name="case-1/raw/evidence.json", content=b"a")
    store.put(tenant_id="tenant-b", object_name="case-1/raw/evidence.json", content=b"b")

    assert set(client.objects) == {
        "tenants/tenant-a/case-1/raw/evidence.json",
        "tenants/tenant-b/case-1/raw/evidence.json",
    }
    _, tenant_a_content = store.get_verified(
        tenant_id="tenant-a", object_name="case-1/raw/evidence.json"
    )
    _, tenant_b_content = store.get_verified(
        tenant_id="tenant-b", object_name="case-1/raw/evidence.json"
    )
    assert tenant_a_content == b"a"
    assert tenant_b_content == b"b"


@pytest.mark.skipif(
    not (
        os.getenv("RECLAIM_MINIO_ENDPOINT")
        and os.getenv("RECLAIM_MINIO_ACCESS_KEY")
        and os.getenv("RECLAIM_MINIO_SECRET_KEY")
    ),
    reason="MinIO endpoint and credentials are required for live validation",
)
def test_live_minio_fixture_checksum_round_trip_if_configured() -> None:
    from minio import Minio

    client = Minio(
        os.environ["RECLAIM_MINIO_ENDPOINT"],
        access_key=os.environ["RECLAIM_MINIO_ACCESS_KEY"],
        secret_key=os.environ["RECLAIM_MINIO_SECRET_KEY"],
        secure=False,
    )
    store = ImmutableEvidenceStore(client)
    raw = EVIDENCE_FIXTURE.read_bytes()
    object_name = f"t036-{os.getpid()}/session-observation.json"
    stored = store.put(tenant_id="tenant-a", object_name=object_name, content=raw)
    verified, content = store.get_verified(tenant_id="tenant-a", object_name=object_name)

    assert verified.checksum == stored.checksum
    assert content == raw
