"""Policy, audit, Vault and bounded-cache orchestration for secret resolution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import SecretStr

from .contracts import SecretBundle, SecretRequest
from .policy import PolicyDenied, SecretPolicy


class SecretForbidden(PermissionError):
    """Uniform 403 result for unknown and unauthorized requests."""


class SecretUnavailable(RuntimeError):
    """Authorized secret could not be read or audited."""


class SecretAudit(Protocol):
    def record(self, **event: object) -> None: ...


class SecretVault(Protocol):
    def read(self, path: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    expires_at: float
    bundle: SecretBundle


class SecretBrokerService:
    def __init__(
        self,
        policy: SecretPolicy,
        *,
        vault: SecretVault,
        audit: SecretAudit | Any,
        clock: Any = time.monotonic,
    ) -> None:
        self.policy = policy
        self.vault = vault
        self.audit = audit
        self.clock = clock
        self._cache: dict[tuple[str, str | None, str], _CacheEntry] = {}

    def resolve(
        self,
        *,
        identity_uri: str,
        request: SecretRequest,
        request_id: str,
    ) -> SecretBundle:
        try:
            definition, tenant_id = self.policy.authorize(
                identity_uri, request.secret_id, request.tenant_id
            )
        except (PolicyDenied, ValueError) as exc:
            raise SecretForbidden("secret access forbidden") from exc

        cache_key = (identity_uri, tenant_id, definition.secret_id)
        self._record(
            event_kind="access_intent",
            identity_uri=identity_uri,
            tenant_id=tenant_id,
            secret_id=definition.secret_id,
            secret_version=None,
            request_id=request_id,
            outcome="accepted",
        )
        cached = self._cache.get(cache_key)
        if cached is not None and cached.expires_at > self.clock():
            self._record(
                event_kind="delivery",
                identity_uri=identity_uri,
                tenant_id=tenant_id,
                secret_id=definition.secret_id,
                secret_version=cached.bundle.version,
                request_id=request_id,
                outcome="released",
            )
            return cached.bundle

        try:
            raw = self.vault.read(definition.vault_path)
            if not raw:
                raise RuntimeError("empty secret")
            version = raw.get("_version", 1)
            values = {key: value for key, value in raw.items() if not key.startswith("_")}
            bundle = SecretBundle(
                secret_id=definition.secret_id,
                version=version,
                cache_ttl_seconds=definition.cache_ttl_seconds,
                values={key: SecretStr(str(value)) for key, value in values.items()},
            )
        except Exception as exc:
            raise SecretUnavailable("secret temporarily unavailable") from exc

        try:
            self._record(
                event_kind="delivery",
                identity_uri=identity_uri,
                tenant_id=tenant_id,
                secret_id=definition.secret_id,
                secret_version=bundle.version,
                request_id=request_id,
                outcome="released",
            )
        except Exception as exc:
            raise SecretUnavailable("secret temporarily unavailable") from exc
        self._cache[cache_key] = _CacheEntry(
            expires_at=self.clock() + definition.cache_ttl_seconds,
            bundle=bundle,
        )
        return bundle

    def _record(self, **event: object) -> None:
        event.setdefault("event_id", str(uuid.uuid4()))
        try:
            record = getattr(self.audit, "record", None)
            if callable(record):
                record(**event)
            elif callable(self.audit):
                self.audit(**event)
            else:
                raise TypeError("secret audit sink is unavailable")
        except Exception as exc:
            raise SecretUnavailable("secret temporarily unavailable") from exc


class PostgresSecretAudit:
    """Insert-only audit sink; secret values never enter this SQL boundary."""

    def __init__(self, connection_factory: Any) -> None:
        self._connection_factory = connection_factory

    def record(self, **event: object) -> None:
        allowed = {
            "event_id",
            "identity_uri",
            "tenant_id",
            "secret_id",
            "secret_version",
            "request_id",
            "event_kind",
            "outcome",
        }
        if set(event) - allowed:
            raise ValueError("secret audit event contains unsupported fields")
        with self._connection_factory() as connection:
            tenant_id = event.get("tenant_id")
            if tenant_id is not None:
                connection.execute(
                    "SELECT set_config('reclaim.tenant_id', %s, true)",
                    (str(tenant_id),),
                )
            connection.execute(
                """
                INSERT INTO public.secret_access_events
                    (event_id, caller_identity, tenant_id, scope, secret_id,
                     secret_version, request_id, event_kind, outcome)
                VALUES (%(event_id)s, %(identity_uri)s, %(tenant_id)s, 'broker',
                        %(secret_id)s, %(secret_version)s, %(request_id)s,
                        %(event_kind)s, %(outcome)s)
                """,
                event,
            )
