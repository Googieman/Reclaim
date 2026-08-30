"""Tenant-scoped Redis cache, lock, rate-limit, and coordination helpers.

No API in this module represents case, financial, policy, action, or terminal
business state.  PostgreSQL remains the correctness boundary when Redis is down.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any, Protocol

from app.db.tenant_context import require_tenant_id


class RedisClient(Protocol):
    def get(self, name: str) -> Any: ...

    def set(self, name: str, value: Any, **kwargs: Any) -> Any: ...

    def delete(self, name: str) -> Any: ...

    def incr(self, name: str) -> int: ...

    def expire(self, name: str, time: int) -> Any: ...


class CoordinationUnavailable(RuntimeError):
    """Raised when bounded coordination cannot be reached."""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    count: int
    limit: int
    retry_after_seconds: int


class RedisLock:
    def __init__(
        self,
        coordinator: RedisCoordinator,
        key: str,
        token: str,
        ttl_seconds: int,
    ) -> None:
        self._coordinator = coordinator
        self.key = key
        self.token = token
        self.ttl_seconds = ttl_seconds
        self.acquired = False

    def __enter__(self) -> RedisLock:
        self.acquired = self._coordinator._set(self.key, self.token, nx=True, ex=self.ttl_seconds)
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.acquired:
            self._coordinator._delete(self.key)
            self.acquired = False


class RedisCoordinator:
    """Explicitly bounded coordination namespace scoped by tenant."""

    def __init__(self, client: RedisClient, *, tenant_id: str, max_ttl_seconds: int = 3600) -> None:
        self.client = client
        self.tenant_id = require_tenant_id(tenant_id)
        if max_ttl_seconds < 1:
            raise ValueError("max_ttl_seconds must be positive")
        self.max_ttl_seconds = max_ttl_seconds

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        tenant_id: str,
        max_ttl_seconds: int = 3600,
    ) -> RedisCoordinator:
        from redis import Redis

        return cls(
            Redis.from_url(url, decode_responses=True),
            tenant_id=tenant_id,
            max_ttl_seconds=max_ttl_seconds,
        )

    def cache_set(self, name: str, value: Any, *, ttl_seconds: int = 300) -> None:
        self._set(
            self._key("cache", name),
            json.dumps(value, sort_keys=True),
            ex=self._ttl(ttl_seconds),
        )

    def cache_get(self, name: str) -> Any | None:
        raw = self._get(self._key("cache", name))
        return None if raw is None else json.loads(raw)

    def lock(self, name: str, *, ttl_seconds: int = 60) -> RedisLock:
        return RedisLock(
            self,
            self._key("lock", name),
            secrets.token_urlsafe(24),
            self._ttl(ttl_seconds),
        )

    def rate_limit(self, name: str, *, limit: int, window_seconds: int = 60) -> RateLimitDecision:
        if limit < 1:
            raise ValueError("rate-limit limit must be positive")
        window = self._ttl(window_seconds)
        key = self._key("rate", name)
        count = self._incr(key)
        if count == 1:
            self._expire(key, window)
        return RateLimitDecision(count <= limit, count, limit, window if count > limit else 0)

    def coordination_set(self, name: str, value: str, *, ttl_seconds: int = 60) -> None:
        """Set an ephemeral coordination hint, never a business-state record."""

        self._set(self._key("coordination", name), value, ex=self._ttl(ttl_seconds))

    def coordination_get(self, name: str) -> str | None:
        raw = self._get(self._key("coordination", name))
        return None if raw is None else str(raw)

    def _key(self, kind: str, name: str) -> str:
        if not name.strip() or ":" in name:
            raise ValueError("Redis coordination names must be non-empty and colon-free")
        return f"reclaim:{kind}:{self.tenant_id}:{name}"

    def _ttl(self, ttl_seconds: int) -> int:
        if ttl_seconds < 1:
            raise ValueError("TTL must be positive")
        return min(ttl_seconds, self.max_ttl_seconds)

    def _get(self, key: str) -> Any:
        try:
            return self.client.get(key)
        except Exception as exc:
            raise CoordinationUnavailable("Redis read unavailable") from exc

    def _set(self, key: str, value: Any, **kwargs: Any) -> bool:
        try:
            return bool(self.client.set(key, value, **kwargs))
        except Exception as exc:
            raise CoordinationUnavailable("Redis write unavailable") from exc

    def _delete(self, key: str) -> None:
        try:
            self.client.delete(key)
        except Exception as exc:
            raise CoordinationUnavailable("Redis delete unavailable") from exc

    def _incr(self, key: str) -> int:
        try:
            return int(self.client.incr(key))
        except Exception as exc:
            raise CoordinationUnavailable("Redis increment unavailable") from exc

    def _expire(self, key: str, seconds: int) -> None:
        try:
            self.client.expire(key, seconds)
        except Exception as exc:
            raise CoordinationUnavailable("Redis expiry unavailable") from exc
