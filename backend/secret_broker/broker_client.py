"""Small in-memory client for named broker bundles."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .contracts import SecretBundle, SecretRequest


@dataclass(frozen=True, slots=True)
class _ClientCacheEntry:
    expires_at: float
    bundle: SecretBundle


class SecretBrokerClient:
    """Fetch one named bundle through an injected authenticated transport."""

    def __init__(
        self,
        transport: Callable[[SecretRequest], SecretBundle],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._cache: dict[tuple[str, str | None], _ClientCacheEntry] = {}

    def resolve(self, request: SecretRequest) -> SecretBundle:
        key = (request.secret_id, request.tenant_id)
        cached = self._cache.get(key)
        if cached is not None and cached.expires_at > self._clock():
            return cached.bundle
        bundle = self._transport(request)
        if not 1 <= bundle.cache_ttl_seconds <= 300:
            raise ValueError("broker returned an invalid cache TTL")
        self._cache[key] = _ClientCacheEntry(
            expires_at=self._clock() + bundle.cache_ttl_seconds,
            bundle=bundle,
        )
        return bundle
