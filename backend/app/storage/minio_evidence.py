"""Immutable MinIO object storage with checksum verification."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any, Protocol


class ObjectStorageClient(Protocol):
    def stat_object(self, bucket_name: str, object_name: str) -> Any: ...

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: Any,
        length: int,
        **kwargs: Any,
    ) -> Any: ...

    def get_object(self, bucket_name: str, object_name: str) -> Any: ...


class ObjectIntegrityError(ValueError):
    """Raised when an object is missing, mutable, or has a checksum mismatch."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    tenant_id: str
    bucket: str
    object_name: str
    checksum: str
    size: int
    content_type: str


def checksum_for_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


class ImmutableEvidenceStore:
    """Store raw evidence under a tenant prefix; normalized facts stay in PostgreSQL."""

    _SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")

    def __init__(self, client: ObjectStorageClient, *, bucket: str = "reclaim-evidence") -> None:
        if not self._SAFE_SEGMENT.fullmatch(bucket):
            raise ValueError("bucket name contains unsupported characters")
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        bucket: str = "reclaim-evidence",
    ) -> ImmutableEvidenceStore:
        from minio import Minio

        return cls(
            Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure),
            bucket=bucket,
        )

    def put(
        self,
        *,
        tenant_id: str,
        object_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        expected_checksum: str | None = None,
    ) -> StoredObject:
        self._ensure_bucket()
        key = self._tenant_key(tenant_id, object_name)
        actual_checksum = checksum_for_bytes(content)
        if expected_checksum is not None and (
            _normalize_checksum(expected_checksum) != actual_checksum
        ):
            raise ObjectIntegrityError("evidence checksum does not match content")

        try:
            existing = self.client.stat_object(self.bucket, key)
        except Exception as exc:
            if not _is_missing_object(exc):
                raise
        else:
            existing_checksum = _metadata_checksum(existing)
            if existing_checksum != actual_checksum or int(existing.size) != len(content):
                raise ObjectIntegrityError(
                    "immutable evidence object already contains different content"
                )
            return StoredObject(
                tenant_id=tenant_id,
                bucket=self.bucket,
                object_name=key,
                checksum=actual_checksum,
                size=len(content),
                content_type=content_type,
            )

        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(content),
            len(content),
            content_type=content_type,
            metadata={"x-amz-meta-sha256": actual_checksum.removeprefix("sha256:")},
        )
        return StoredObject(
            tenant_id,
            self.bucket,
            key,
            actual_checksum,
            len(content),
            content_type,
        )

    def _ensure_bucket(self) -> None:
        bucket_exists = getattr(self.client, "bucket_exists", None)
        make_bucket = getattr(self.client, "make_bucket", None)
        if bucket_exists is None or make_bucket is None:
            return
        if bucket_exists(self.bucket):
            return
        try:
            make_bucket(self.bucket)
        except Exception as exc:
            if getattr(exc, "code", None) not in {
                "BucketAlreadyOwnedByYou",
                "BucketAlreadyExists",
            }:
                raise

    def get_verified(self, *, tenant_id: str, object_name: str) -> tuple[StoredObject, bytes]:
        key = self._tenant_key(tenant_id, object_name)
        response = self.client.get_object(self.bucket, key)
        try:
            content = response.read()
            metadata_checksum = _metadata_checksum(response)
        finally:
            response.close()
            release = getattr(response, "release_conn", None)
            if release is not None:
                release()
        actual_checksum = checksum_for_bytes(content)
        if metadata_checksum != actual_checksum:
            raise ObjectIntegrityError("stored evidence checksum mismatch")
        return (
            StoredObject(tenant_id, self.bucket, key, actual_checksum, len(content), ""),
            content,
        )

    def _tenant_key(self, tenant_id: str, object_name: str) -> str:
        if not self._SAFE_SEGMENT.fullmatch(tenant_id):
            raise ValueError("tenant_id contains unsupported object path characters")
        parts = object_name.replace("\\", "/").split("/")
        if not parts or any(
            part in {"", ".", ".."} or not self._SAFE_SEGMENT.fullmatch(part) for part in parts
        ):
            raise ValueError("object_name must be a safe relative object path")
        return "/".join(("tenants", tenant_id, *parts))


def _normalize_checksum(value: str) -> str:
    value = value.strip().lower()
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _metadata_checksum(metadata: Any) -> str:
    for attribute in ("metadata", "headers"):
        raw = getattr(metadata, attribute, {}) or {}
        for key, value in raw.items():
            if key.lower().removeprefix("x-amz-meta-") in {"sha256", "checksum"}:
                return _normalize_checksum(str(value))
    checksum = getattr(metadata, "etag", None)
    if checksum:
        return _normalize_checksum(str(checksum).strip('"'))
    raise ObjectIntegrityError("stored evidence object has no checksum metadata")


def _is_missing_object(error: Exception) -> bool:
    code = getattr(error, "code", None)
    return code in {"NoSuchKey", "NoSuchBucket", "NotFound", "NoSuchObject"}
