"""Immutable MinIO object storage with checksum verification."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_settings
from app.payload_limits import PayloadLimitError, enforce_payload_limit


class ObjectStorageClient(Protocol):
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


class ObjectPayloadLimitError(ObjectIntegrityError):
    """Raised before an oversized object can reach the object-storage client."""


class ObjectAlreadyExists(Exception):
    """Atomic-create conflict used by deterministic object-storage doubles."""

    code = "PreconditionFailed"


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

    def __init__(
        self,
        client: ObjectStorageClient,
        *,
        bucket: str = "reclaim-evidence",
        max_payload_bytes: int | None = None,
    ) -> None:
        if not self._SAFE_SEGMENT.fullmatch(bucket):
            raise ValueError("bucket name contains unsupported characters")
        self.client = client
        self.bucket = bucket
        self.max_payload_bytes = (
            get_settings().raw_object_max_bytes if max_payload_bytes is None else max_payload_bytes
        )
        if self.max_payload_bytes < 1:
            raise ValueError("raw object payload limit must be positive")

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
        try:
            enforce_payload_limit(
                content,
                max_bytes=self.max_payload_bytes,
                label="raw evidence",
            )
        except PayloadLimitError as exc:
            raise ObjectPayloadLimitError(
                "raw evidence payload exceeds configured size limit"
            ) from exc
        key = self._tenant_key(tenant_id, object_name)
        actual_checksum = checksum_for_bytes(content)
        if expected_checksum is not None and (
            _normalize_checksum(expected_checksum) != actual_checksum
        ):
            raise ObjectIntegrityError("evidence checksum does not match content")

        self._ensure_bucket()
        try:
            created = self._atomic_create(
                key=key,
                content=content,
                content_type=content_type,
                checksum=actual_checksum,
            )
        except Exception as exc:
            if not _is_atomic_conflict(exc):
                raise
            created = False

        # A failed conditional create means a concurrent or previous writer
        # owns the key.  Read and hash the stored bytes before accepting an
        # identical duplicate; a different value fails closed.
        if not created:
            return self._verified_existing(
                tenant_id=tenant_id,
                key=key,
                content=content,
                checksum=actual_checksum,
                content_type=content_type,
            )

        return self._verified_existing(
            tenant_id=tenant_id,
            key=key,
            content=content,
            checksum=actual_checksum,
            content_type=content_type,
        )

    def _atomic_create(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        checksum: str,
    ) -> bool:
        """Create exactly once using the client atomic-create capability."""

        atomic_create = getattr(self.client, "put_object_if_absent", None)
        if callable(atomic_create):
            result = atomic_create(
                self.bucket,
                key,
                io.BytesIO(content),
                len(content),
                content_type=content_type,
                metadata={"x-amz-meta-sha256": checksum.removeprefix("sha256:")},
            )
            return result is not False

        # MinIO's Python SDK exposes the signed request executor but not an
        # If-None-Match option on put_object.  The S3 conditional PUT is the
        # server-side atomic operation; never fall back to stat-then-put.
        execute = getattr(self.client, "_execute", None)
        if callable(execute):
            response = execute(
                "PUT",
                bucket_name=self.bucket,
                object_name=key,
                body=content,
                headers={
                    "Content-Type": content_type,
                    "If-None-Match": "*",
                    "X-Amz-Meta-Sha256": checksum.removeprefix("sha256:"),
                },
                no_body_trace=True,
            )
            _release_response(response)
            return True

        raise ObjectIntegrityError("object storage client lacks atomic immutable-create support")

    def _verified_existing(
        self,
        *,
        tenant_id: str,
        key: str,
        content: bytes,
        checksum: str,
        content_type: str,
    ) -> StoredObject:
        try:
            stored, existing_content = self.get_verified(
                tenant_id=tenant_id,
                object_name=key.removeprefix(f"tenants/{tenant_id}/"),
            )
        except Exception as exc:
            raise ObjectIntegrityError(
                "immutable evidence object could not be verified after atomic create"
            ) from exc
        if existing_content != content or stored.checksum != checksum:
            raise ObjectIntegrityError(
                "immutable evidence object already contains different content"
            )
        return StoredObject(
            tenant_id,
            self.bucket,
            key,
            checksum,
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


def _is_atomic_conflict(error: Exception) -> bool:
    return getattr(error, "code", None) in {
        "PreconditionFailed",
        "ConditionalRequestConflict",
    } or getattr(error, "status", None) in {409, 412}


def _release_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if close is not None:
        close()
    release = getattr(response, "release_conn", None)
    if release is not None:
        release()
