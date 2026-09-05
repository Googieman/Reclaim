"""Versioned public contract for the private secret broker."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_id: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", max_length=128)
    tenant_id: str | None = Field(default=None, max_length=128)


class SecretBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_id: str
    version: int = Field(ge=1)
    cache_ttl_seconds: int = Field(ge=1, le=300)
    values: dict[str, SecretStr]

    def to_delivery_dict(self) -> dict[str, object]:
        """Materialize values only at the authenticated broker response boundary."""

        return {
            "secret_id": self.secret_id,
            "version": self.version,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "values": {name: value.get_secret_value() for name, value in self.values.items()},
        }
