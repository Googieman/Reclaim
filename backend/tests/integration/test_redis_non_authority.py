"""Redis helpers are bounded coordination and never business state."""

import os
from typing import Any

from app.coordination.redis import RedisCoordinator


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.expiries: dict[str, int] = {}

    def get(self, name: str) -> Any:
        return self.values.get(name)

    def set(self, name: str, value: Any, **kwargs: Any) -> bool:
        if kwargs.get("nx") and name in self.values:
            return False
        self.values[name] = value
        if "ex" in kwargs:
            self.expiries[name] = kwargs["ex"]
        return True

    def delete(self, name: str) -> int:
        self.values.pop(name, None)
        return 1

    def incr(self, name: str) -> int:
        self.values[name] = int(self.values.get(name, 0)) + 1
        return self.values[name]

    def expire(self, name: str, time: int) -> bool:
        self.expiries[name] = time
        return True


def test_cache_lock_and_rate_limit_are_tenant_scoped_and_bounded() -> None:
    redis = FakeRedis()
    coordinator = RedisCoordinator(redis, tenant_id="tenant-a", max_ttl_seconds=30)
    coordinator.cache_set("case", {"hint": "temporary"}, ttl_seconds=300)
    decision = coordinator.rate_limit("intake", limit=1, window_seconds=60)
    with coordinator.lock("case") as lock:
        assert lock.acquired

    assert coordinator.cache_get("case") == {"hint": "temporary"}
    assert decision.allowed
    assert redis.expiries["reclaim:cache:tenant-a:case"] == 30
    assert "reclaim:case" not in redis.values
    assert not hasattr(coordinator, "set_case_state")


def test_live_redis_coordination_if_service_is_configured() -> None:
    url = os.getenv("RECLAIM_REDIS_URL")
    if not url:
        import pytest

        pytest.skip("RECLAIM_REDIS_URL is required for live Redis validation")
    coordinator = RedisCoordinator.from_url(url, tenant_id="tenant-a", max_ttl_seconds=30)
    coordinator.cache_set("live-check", {"kind": "coordination"}, ttl_seconds=10)
    assert coordinator.cache_get("live-check") == {"kind": "coordination"}
