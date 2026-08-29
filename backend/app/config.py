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
