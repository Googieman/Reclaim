"""Common fields and validation shared by all FS-001 contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = "1.0.0"


class ContractModel(BaseModel):
    """Strict contract model with mandatory tenant and correlation context."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    schema_version: str = Field(default=CONTRACT_VERSION, min_length=1)
    tenant_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)

    @field_validator("schema_version", "tenant_id", "correlation_id")
    @classmethod
    def reject_blank_context(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("contract context values cannot be blank")
        return value


def require_utc(value: datetime | None) -> datetime | None:
    """Require timezone-aware timestamps and normalize them to UTC."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include an explicit timezone")
    return value.astimezone(timezone.utc)


class TimestampedContract(ContractModel):
    """Contract carrying the event/request receipt timestamp."""

    occurred_at: datetime

    _normalize_occurred_at = field_validator("occurred_at")(require_utc)


class Reference(BaseModel):
    """An auditable reference to an input, evidence item, or output."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reference_id: str = Field(min_length=1)
    reference_type: str = Field(min_length=1)
    checksum: str | None = None


JsonObject = dict[str, Any]
