"""Typed, non-secret runtime configuration for the RECLAIM services."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings with safe replay and action defaults."""

    model_config = SettingsConfigDict(
        env_prefix="RECLAIM_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "reclaim-backend"
    environment: Literal["development", "test", "production"] = "development"
    tenant_id: str = Field(default="demo-tenant", min_length=1)
    run_mode: Literal["live", "replay"] = "replay"
    replay_label: Literal["live", "replay"] = "replay"
    live_actions_enabled: bool = False
    live_financial_actions_enabled: bool = False

    # Payload limits are byte limits at trust/storage boundaries.  Connector
    # response limits remain declared by each ConnectorManifest; these values
    # protect the shared intake and object-storage boundaries.
    incident_report_max_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    webhook_max_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    raw_object_max_bytes: int = Field(default=16_777_216, ge=1, le=16_777_216)

    database_url: str = "postgresql://reclaim:reclaim@localhost:5432/reclaim"
    temporal_target: str = "localhost:7233"
    redpanda_brokers: str = "localhost:9092"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    keycloak_issuer: str = "http://localhost:8080/realms/reclaim"
    vault_address: str = "http://localhost:8200"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""

    return Settings()
