"""Immutable MinIO object and checksum tests."""

import os
from io import BytesIO

import pytest
from app.storage.minio_evidence import (
    ImmutableEvidenceStore,
    ObjectIntegrityError,
    checksum_for_bytes,
)


class MissingObject(Exception):
    code = "NoSuchKey"


class Stat:
    def __init__(self, content: bytes) -> None:
        self.size = len(content)
        self.metadata = {"X-Amz-Meta-Sha256": checksum_for_bytes(content).removeprefix("sha256:")}


class Response:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.metadata = {"X-Amz-Meta-Sha256": checksum_for_bytes(content).removeprefix("sha256:")}

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def stat_object(self, bucket_name: str, object_name: str) -> Stat:
        if object_name not in self.objects:
            raise MissingObject()
        return Stat(self.objects[object_name])

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        length: int,
        **kwargs: object,
    ) -> None:
        self.objects[object_name] = data.read()

    def get_object(self, bucket_name: str, object_name: str) -> Response:
        return Response(self.objects[object_name])


def test_evidence_is_tenant_prefixed_immutable_and_verified() -> None:
    client = FakeMinio()
    store = ImmutableEvidenceStore(client)
    content = b"evidence"
    stored = store.put(tenant_id="tenant-a", object_name="case-1/raw.json", content=content)
    duplicate = store.put(tenant_id="tenant-a", object_name="case-1/raw.json", content=content)
    verified, result = store.get_verified(tenant_id="tenant-a", object_name="case-1/raw.json")

    assert stored.object_name == "tenants/tenant-a/case-1/raw.json"
    assert duplicate.checksum == stored.checksum
    assert verified.checksum == stored.checksum
    assert result == content

    with pytest.raises(ObjectIntegrityError, match="different content"):
        store.put(tenant_id="tenant-a", object_name="case-1/raw.json", content=b"tampered")


def test_evidence_object_names_cannot_escape_tenant_prefix() -> None:
    with pytest.raises(ValueError, match="safe relative"):
        ImmutableEvidenceStore(FakeMinio()).put(
            tenant_id="tenant-a", object_name="../other/raw.json", content=b"evidence"
        )


def test_live_minio_checksum_round_trip_if_service_is_configured() -> None:
    endpoint = os.getenv("RECLAIM_MINIO_ENDPOINT")
    access_key = os.getenv("RECLAIM_MINIO_ACCESS_KEY")
    secret_key = os.getenv("RECLAIM_MINIO_SECRET_KEY")
    if not (endpoint and access_key and secret_key):
        pytest.skip("MinIO endpoint and credentials are required for live validation")
    from minio import Minio

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
    store = ImmutableEvidenceStore(client)
    object_name = f"live-{os.getpid()}/evidence.bin"
    stored = store.put(tenant_id="tenant-a", object_name=object_name, content=b"live-evidence")
    verified, content = store.get_verified(tenant_id="tenant-a", object_name=object_name)
    assert verified.checksum == stored.checksum
    assert content == b"live-evidence"
