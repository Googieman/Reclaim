"""Typed, non-secret runtime configuration for the RECLAIM services."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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
    environment: Literal[
        "development", "test", "ci", "ci-evaluation", "ci-security", "production"
    ] = "development"
    tenant_id: str = Field(default="demo-tenant", min_length=1)
    run_mode: Literal["live", "replay"] = "replay"
    replay_label: Literal["live", "replay"] = "replay"
    live_actions_enabled: bool = False
    live_financial_actions_enabled: bool = False
    demo_read_only_enabled: bool = False
    authoritative_demo_enabled: bool = False
    fresh_agent_enabled: bool = False
    fresh_agent_profile: str = "reclaim-specialist"
    fresh_agent_action_environment: Literal["simulator", "test_mode", "live_merchant"] = "simulator"
    fresh_agent_fallback_profile: str | None = None
    help_chat_enabled: bool = False
    help_chat_profile: str = "reclaim-help-deepseek"
    agent_max_tokens: int = Field(default=2_048, ge=1, le=100_000)
    agent_max_tool_calls: int = Field(default=4, ge=0, le=100)
    agent_timeout_seconds: int = Field(default=60, ge=1, le=900)

    # Payload limits are byte limits at trust/storage boundaries.  Connector
    # response limits remain declared by each ConnectorManifest; these values
    # protect the shared intake and object-storage boundaries.
    incident_report_max_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    webhook_max_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    raw_object_max_bytes: int = Field(default=16_777_216, ge=1, le=16_777_216)

    # Operational objectives are explicit configuration so deployment tooling can
    # compare measured backup/recovery evidence with the declared targets.
    rpo_minutes: int = Field(default=15, ge=1, le=1440)
    rto_minutes: int = Field(default=60, ge=1, le=1440)
    backup_retention_days: int = Field(default=35, ge=1, le=3650)

    database_url: str = "postgresql://reclaim:reclaim@localhost:5432/reclaim"
    temporal_target: str = "localhost:7233"
    redpanda_brokers: str = "localhost:9092"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    keycloak_issuer: str = "http://localhost:8080/realms/reclaim"
    vault_address: str = "http://localhost:8200"
    minio_access_key: str = "reclaim"
    minio_secret_key: str = "reclaim-development"
    minio_secure: bool = False
    oidc_audience: str = "reclaim-api"
    oidc_jwks_url: str | None = None
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    orchestration_provider: Literal["n8n"] = "n8n"
    n8n_api_base_url: str = "http://n8n-main:5678"
    n8n_workflow_version: str = "incident-analysis-handoff.v1"
    redpanda_security_protocol: Literal["PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"] = (
        "PLAINTEXT"
    )
    redpanda_sasl_mechanism: Literal["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"] = "PLAIN"
    redpanda_sasl_username: str | None = None
    redpanda_sasl_password: str | None = None
    redpanda_sasl_password_file: str | None = None
    redpanda_tls_ca_file: str | None = None
    redpanda_tls_cert_file: str | None = None
    redpanda_tls_key_file: str | None = None
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_poll_interval_seconds: float = Field(default=1.0, gt=0.0, le=300.0)
    outbox_error_backoff_seconds: float = Field(default=5.0, gt=0.0, le=300.0)

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Require deployment-provided identity and broker security in production."""

        if self.demo_read_only_enabled and (
            self.environment == "production"
            or self.run_mode != "replay"
            or self.replay_label != "replay"
            or self.live_actions_enabled
            or self.live_financial_actions_enabled
        ):
            raise ValueError(
                "read-only demo requires a non-production REPLAY configuration "
                "with live actions off"
            )
        if self.live_actions_enabled or self.live_financial_actions_enabled:
            raise ValueError("live actions are not qualified and must remain disabled")
        if self.environment != "production":
            return self
        # No demo application is mounted in production, but retain this branch so
        # the application-level guard has the same stable contract if reused.
        if self.demo_read_only_enabled:
            return self
        missing_oidc = not self.oidc_audience.strip() or not self.oidc_jwks_url
        if missing_oidc or not self.oidc_jwks_url.startswith("https://"):
            raise ValueError("production OIDC issuer, audience, and HTTPS JWKS URL are required")
        if tuple(self.oidc_algorithms) != ("RS256",):
            raise ValueError("production OIDC must use the RS256 algorithm")
        if not self.vault_address.startswith("https://"):
            raise ValueError("production Vault address must use HTTPS")
        if not self.keycloak_issuer.startswith("https://"):
            raise ValueError("production Keycloak issuer must use HTTPS")
        if self.redpanda_security_protocol != "SASL_SSL":
            raise ValueError("production Redpanda must use SASL_SSL")
        if not self.redpanda_sasl_username or not (
            self.redpanda_sasl_password or self.redpanda_sasl_password_file
        ):
            raise ValueError("production Redpanda SASL credentials are required")
        if not all(
            (self.redpanda_tls_ca_file, self.redpanda_tls_cert_file, self.redpanda_tls_key_file)
        ):
            raise ValueError("production Redpanda client TLS files are required")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""

    return Settings()
