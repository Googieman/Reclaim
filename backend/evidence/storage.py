"""Raw evidence storage adapters and deterministic object-storage test double."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from app.auth.oidc import TenantAuthorizationContext, TenantAuthorizationError
from app.storage.minio_evidence import (
    ImmutableEvidenceStore,
    ObjectIntegrityError,
    StoredObject,
)


@dataclass(frozen=True, slots=True)
class RawEvidenceArtifact:
    tenant_id: str
    case_id: str
    evidence_id: str
    object_uri: str
    checksum: str
    size: int


class InMemoryObjectStorage:
    """Object-storage-compatible deterministic double for unit and replay tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def stat_object(self, bucket_name: str, object_name: str) -> Any:
        del bucket_name
        try:
            content, checksum = self.objects[object_name]
        except KeyError as exc:
            raise _MissingObject() from exc
        return _ObjectStat(content, checksum)

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        length: int,
        **kwargs: Any,
    ) -> None:
        del bucket_name
        content = data.read()
        if length != len(content):
            raise ValueError("object length does not match content")
        checksum = str((kwargs.get("metadata") or {}).get("x-amz-meta-sha256", ""))
        if not checksum:
            from app.storage.minio_evidence import checksum_for_bytes

            checksum = checksum_for_bytes(content).removeprefix("sha256:")
        self.objects[object_name] = (content, f"sha256:{checksum}")

    def get_object(self, bucket_name: str, object_name: str) -> Any:
        del bucket_name
        content, checksum = self.objects[object_name]
        return _ObjectResponse(content, checksum)


class EvidenceStorage:
    """Persist immutable raw bytes under an authenticated tenant/case prefix."""

    def __init__(self, store: ImmutableEvidenceStore) -> None:
        self.store = store

    def persist_raw(
        self,
        *,
        authorization_context: TenantAuthorizationContext,
        case_id: str,
        evidence_id: str,
        resource_type: str,
        raw_payload: bytes,
        expected_checksum: str | None,
    ) -> RawEvidenceArtifact:
        if not isinstance(authorization_context, TenantAuthorizationContext):
            raise TenantAuthorizationError("raw evidence storage requires tenant authorization")
        if not case_id.strip() or not evidence_id.strip() or not resource_type.strip():
            raise ValueError("case, evidence, and resource identity are required")
        object_name = f"{case_id}/raw/{resource_type}/{evidence_id}.json"
        stored: StoredObject = self.store.put(
            tenant_id=authorization_context.tenant_id,
            object_name=object_name,
            content=raw_payload,
            expected_checksum=expected_checksum,
            content_type="application/json",
        )
        return RawEvidenceArtifact(
            tenant_id=authorization_context.tenant_id,
            case_id=case_id,
            evidence_id=evidence_id,
            object_uri=f"minio://{stored.bucket}/{stored.object_name}",
            checksum=stored.checksum,
            size=stored.size,
        )


class _ObjectStat:
    def __init__(self, content: bytes, checksum: str) -> None:
        self.size = len(content)
        self.metadata = {"X-Amz-Meta-Sha256": checksum.removeprefix("sha256:")}


class _MissingObject(Exception):
    code = "NoSuchKey"


class _ObjectResponse:
    def __init__(self, content: bytes, checksum: str) -> None:
        self.content = content
        self.metadata = {"X-Amz-Meta-Sha256": checksum.removeprefix("sha256:")}

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


__all__ = [
    "EvidenceStorage",
    "InMemoryObjectStorage",
    "ObjectIntegrityError",
    "RawEvidenceArtifact",
]
