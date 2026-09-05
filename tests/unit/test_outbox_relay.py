"""Unit tests for the PostgreSQL outbox relay loop."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import psycopg
from aiokafka.errors import KafkaConnectionError
from app.auth.oidc import IdentityType
from app.config import Settings
from app.db.repositories.base import RepositoryError
from pydantic import ValidationError

from app.events.outbox_relay import relay_authorization_context, run_relay


def relay_settings() -> Settings:
    return Settings(
        tenant_id="tenant-relay",
        redpanda_brokers="redpanda:9092",
        outbox_batch_size=25,
        outbox_poll_interval_seconds=2.5,
        outbox_error_backoff_seconds=7.0,
    )


def fake_uow_factory(_authorization_context: object) -> "_FakeUnitOfWork":
    return _FakeUnitOfWork()


class _FakeUnitOfWork:
    def __enter__(self) -> "_FakeUnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


class StopAfterSleeps:
    def __init__(self, count: int) -> None:
        self.count = count
        self.delays: list[float] = []

    def __call__(self) -> bool:
        return len(self.delays) >= self.count

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


class ManualStop:
    def __init__(self) -> None:
        self.requested = False

    def __call__(self) -> bool:
        return self.requested

    def request(self) -> None:
        self.requested = True


class StopDuringSleep:
    def __init__(self, stop: ManualStop) -> None:
        self.stop = stop
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        self.stop.request()


class StubPublisher:
    def __init__(self, outcomes: list[Exception | Callable[[], object] | object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.contexts: list[object] = []
        self.limits: list[int] = []
        self.published_at: list[datetime] = []

    async def publish_pending(
        self,
        *,
        unit_of_work_factory: object,
        authorization_context: object,
        limit: int,
        published_at: datetime,
    ) -> tuple[object, ...]:
        del unit_of_work_factory
        self.calls += 1
        self.contexts.append(authorization_context)
        self.limits.append(limit)
        self.published_at.append(published_at)

        outcome = self._outcomes.pop(0) if self._outcomes else ()
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            result = outcome()
        else:
            result = outcome
        if result is None:
            return ()
        if isinstance(result, tuple):
            return result
        if isinstance(result, list):
            return tuple(result)
        return (result,)


class RecordingProducer:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.bootstrap_servers: str | None = None
        self.start_error = start_error

    async def start(self) -> None:
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error

    async def stop(self) -> None:
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_relay_uses_one_owned_producer_lifecycle_per_process() -> None:
    settings = relay_settings()
    producer = RecordingProducer()
    stop = ManualStop()

    def producer_factory(*, bootstrap_servers: str) -> RecordingProducer:
        producer.bootstrap_servers = bootstrap_servers
        return producer

    def stop_after_first_publish() -> tuple[object, ...]:
        stop.request()
        return (SimpleNamespace(event_id="event-1"),)

    publisher = StubPublisher([stop_after_first_publish])
    publisher_factory_calls: list[object] = []

    def publisher_factory(created_producer: object) -> StubPublisher:
        publisher_factory_calls.append(created_producer)
        return publisher

    await run_relay(
        settings=settings,
        producer_factory=producer_factory,
        publisher_factory=publisher_factory,
        unit_of_work_factory=fake_uow_factory,
        should_stop=stop,
        now=lambda: datetime(2026, 9, 4, 9, 0, tzinfo=UTC),
    )

    assert producer.bootstrap_servers == settings.redpanda_brokers
    assert producer.start_calls == 1
    assert producer.stop_calls == 1
    assert publisher_factory_calls == [producer]


def test_relay_authorization_context_is_tenant_bound_and_allowlisted() -> None:
    context = relay_authorization_context(relay_settings())

    assert context.subject == "reclaim-event-relay"
    assert context.tenant_id == relay_settings().tenant_id
    assert context.roles == frozenset({"service"})
    assert context.identity_type is IdentityType.SERVICE
    assert context.issuer == "local-runtime"


@pytest.mark.asyncio
async def test_relay_publishes_with_tenant_context_and_batch_limit() -> None:
    settings = relay_settings()
    stop = ManualStop()
    publisher = StubPublisher(
        [
            lambda: (
                stop.request(),
                (SimpleNamespace(event_id="event-1"),),
            )[1]
        ]
    )
    published_at = datetime(2026, 9, 4, 9, 30, tzinfo=UTC)

    await run_relay(
        settings=settings,
        publisher=publisher,
        unit_of_work_factory=fake_uow_factory,
        should_stop=stop,
        now=lambda: published_at,
    )

    assert publisher.calls == 1
    assert publisher.limits == [settings.outbox_batch_size]
    assert publisher.published_at == [published_at]
    context = publisher.contexts[0]
    assert context.subject == "reclaim-event-relay"
    assert context.tenant_id == settings.tenant_id
    assert context.roles == frozenset({"service"})
    assert context.identity_type is IdentityType.SERVICE
    assert context.issuer == "local-runtime"


@pytest.mark.asyncio
async def test_relay_sleeps_for_poll_interval_when_no_rows_are_published() -> None:
    stop = StopAfterSleeps(1)
    publisher = StubPublisher([()])

    await run_relay(
        settings=relay_settings(),
        publisher=publisher,
        unit_of_work_factory=fake_uow_factory,
        sleep=stop.sleep,
        should_stop=stop,
    )

    assert publisher.calls == 1
    assert stop.delays == [relay_settings().outbox_poll_interval_seconds]


@pytest.mark.asyncio
async def test_relay_retries_without_watermarking_a_failed_publish() -> None:
    stop = ManualStop()
    sleep = StopAfterSleeps(1)
    publisher = StubPublisher(
        [
            KafkaConnectionError("broker unavailable"),
            lambda: (
                stop.request(),
                (),
            )[1],
        ]
    )

    await run_relay(
        settings=relay_settings(),
        publisher=publisher,
        unit_of_work_factory=fake_uow_factory,
        sleep=sleep.sleep,
        should_stop=stop,
    )

    assert publisher.calls == 2
    assert sleep.delays == [relay_settings().outbox_error_backoff_seconds]


@pytest.mark.asyncio
async def test_relay_stops_cleanly_when_shutdown_requested_during_error_backoff() -> None:
    stop = ManualStop()
    sleep = StopDuringSleep(stop)
    publisher = StubPublisher([KafkaConnectionError("broker unavailable")])

    await run_relay(
        settings=relay_settings(),
        publisher=publisher,
        unit_of_work_factory=fake_uow_factory,
        sleep=sleep,
        should_stop=stop,
    )

    assert publisher.calls == 1
    assert sleep.delays == [relay_settings().outbox_error_backoff_seconds]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_factory",),
    [
        (lambda: KafkaConnectionError("broker unavailable"),),
        (lambda: psycopg.OperationalError("postgres unavailable"),),
    ],
)
async def test_relay_retries_recoverable_transport_and_database_errors(
    error_factory: Callable[[], Exception],
) -> None:
    stop = ManualStop()
    sleep = StopAfterSleeps(1)
    publisher = StubPublisher(
        [
            error_factory(),
            lambda: (
                stop.request(),
                (),
            )[1],
        ]
    )

    await run_relay(
        settings=relay_settings(),
        publisher=publisher,
        unit_of_work_factory=fake_uow_factory,
        sleep=sleep.sleep,
        should_stop=stop,
    )

    assert publisher.calls == 2
    assert sleep.delays == [relay_settings().outbox_error_backoff_seconds]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_factory", "message"),
    [
        (lambda: ValueError("bad relay contract"), "bad relay contract"),
        (lambda: RepositoryError("repository misuse"), "repository misuse"),
    ],
)
async def test_relay_does_not_retry_unexpected_programming_errors(
    error_factory: Callable[[], Exception],
    message: str,
) -> None:
    publisher = StubPublisher([error_factory()])

    with pytest.raises(type(error_factory()), match=message):
        await run_relay(
            settings=relay_settings(),
            publisher=publisher,
            unit_of_work_factory=fake_uow_factory,
            should_stop=ManualStop(),
        )

    assert publisher.calls == 1


@pytest.mark.asyncio
async def test_relay_closes_an_owned_producer_on_clean_shutdown() -> None:
    producer = RecordingProducer()
    stop = StopAfterSleeps(1)

    def producer_factory(*, bootstrap_servers: str) -> RecordingProducer:
        assert bootstrap_servers == relay_settings().redpanda_brokers
        return producer

    await run_relay(
        settings=relay_settings(),
        producer_factory=producer_factory,
        publisher_factory=lambda created_producer: StubPublisher([()]),
        unit_of_work_factory=fake_uow_factory,
        sleep=stop.sleep,
        should_stop=stop,
    )

    assert producer.start_calls == 1
    assert producer.stop_calls == 1


@pytest.mark.asyncio
async def test_relay_closes_owned_producer_when_startup_fails() -> None:
    producer = RecordingProducer(start_error=KafkaConnectionError("broker unavailable"))

    with pytest.raises(KafkaConnectionError, match="broker unavailable"):
        await run_relay(
            settings=relay_settings(),
            producer_factory=lambda *, bootstrap_servers: producer,
            unit_of_work_factory=fake_uow_factory,
        )

    assert producer.start_calls == 1
    assert producer.stop_calls == 1


@pytest.mark.asyncio
async def test_relay_closes_owned_producer_when_publisher_construction_fails() -> None:
    producer = RecordingProducer()

    def publisher_factory(_created_producer: object) -> StubPublisher:
        raise RuntimeError("publisher wiring failed")

    with pytest.raises(RuntimeError, match="publisher wiring failed"):
        await run_relay(
            settings=relay_settings(),
            producer_factory=lambda *, bootstrap_servers: producer,
            publisher_factory=publisher_factory,
            unit_of_work_factory=fake_uow_factory,
        )

    assert producer.start_calls == 1
    assert producer.stop_calls == 1


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("outbox_poll_interval_seconds", 0.0),
        ("outbox_error_backoff_seconds", 0.0),
    ],
)
def test_relay_settings_reject_zero_timing_bounds(field_name: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(
            tenant_id="tenant-relay",
            redpanda_brokers="redpanda:9092",
            outbox_batch_size=25,
            outbox_poll_interval_seconds=value
            if field_name == "outbox_poll_interval_seconds"
            else relay_settings().outbox_poll_interval_seconds,
            outbox_error_backoff_seconds=value
            if field_name == "outbox_error_backoff_seconds"
            else relay_settings().outbox_error_backoff_seconds,
        )
