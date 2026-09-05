"""Runtime relay from the PostgreSQL outbox to Redpanda."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import psycopg
from aiokafka.errors import KafkaError

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.config import Settings, get_settings
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.redpanda import RedpandaOutboxPublisher

LOGGER = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[object]]
Now = Callable[[], datetime]
UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]
PublisherFactory = Callable[[Any], RedpandaOutboxPublisher]


class StopCheck(Protocol):
    def __call__(self) -> bool: ...


def relay_authorization_context(settings: Settings) -> TenantAuthorizationContext:
    """Return the fixed service identity used by the runtime relay."""

    return TenantAuthorizationContext(
        subject="reclaim-event-relay",
        tenant_id=settings.tenant_id,
        roles=frozenset({"service"}),
        identity_type=IdentityType.SERVICE,
        issuer="local-runtime",
    )


def relay_unit_of_work_factory(settings: Settings) -> UnitOfWorkFactory:
    """Build a tenant-scoped PostgreSQL unit-of-work factory for the relay."""

    connection_factory = _postgres_connection_factory(settings)
    return lambda authorization_context: PostgresUnitOfWork(
        connection_factory,
        authorization_context=authorization_context,
    )


async def run_relay(
    *,
    settings: Settings,
    publisher: RedpandaOutboxPublisher | Any | None = None,
    producer_factory: Callable[..., Any] | None = None,
    publisher_factory: PublisherFactory | None = None,
    unit_of_work_factory: UnitOfWorkFactory | None = None,
    sleep: Sleep = asyncio.sleep,
    should_stop: StopCheck | None = None,
    now: Now | None = None,
) -> None:
    """Poll the authoritative outbox and publish pending rows to Redpanda."""

    authorization_context = relay_authorization_context(settings)
    unit_of_work_factory = unit_of_work_factory or relay_unit_of_work_factory(settings)
    should_stop = should_stop or (lambda: False)
    now = now or (lambda: datetime.now(UTC))
    owned_producer: Any | None = None

    try:
        if publisher is None:
            producer_factory = producer_factory or _default_producer_factory
            publisher_factory = publisher_factory or RedpandaOutboxPublisher
            owned_producer = producer_factory(**_default_producer_kwargs(settings))
            await owned_producer.start()
            publisher = publisher_factory(owned_producer)

        while True:
            if should_stop():
                LOGGER.info(
                    "outbox relay stopping tenant_id=%s subject=%s",
                    authorization_context.tenant_id,
                    authorization_context.subject,
                )
                return
            try:
                published = await publisher.publish_pending(
                    unit_of_work_factory=unit_of_work_factory,
                    authorization_context=authorization_context,
                    limit=settings.outbox_batch_size,
                    published_at=now(),
                )
                if published:
                    LOGGER.info(
                        "outbox relay published count=%s event_ids=%s",
                        len(published),
                        ",".join(item.event_id for item in published),
                    )
                if should_stop():
                    LOGGER.info(
                        "outbox relay stopping tenant_id=%s subject=%s",
                        authorization_context.tenant_id,
                        authorization_context.subject,
                    )
                    return
                if not published:
                    await sleep(settings.outbox_poll_interval_seconds)
                    if should_stop():
                        LOGGER.info(
                            "outbox relay stopping after idle wait tenant_id=%s subject=%s",
                            authorization_context.tenant_id,
                            authorization_context.subject,
                        )
                        return
            except (KafkaError, psycopg.Error) as exc:
                if should_stop():
                    LOGGER.info(
                        "outbox relay stopping after failure tenant_id=%s subject=%s",
                        authorization_context.tenant_id,
                        authorization_context.subject,
                    )
                    return
                LOGGER.warning(
                    "outbox relay publish failed backoff_seconds=%s error_type=%s",
                    settings.outbox_error_backoff_seconds,
                    type(exc).__name__,
                )
                await sleep(settings.outbox_error_backoff_seconds)
                if should_stop():
                    LOGGER.info(
                        "outbox relay stopping after backoff tenant_id=%s subject=%s",
                        authorization_context.tenant_id,
                        authorization_context.subject,
                    )
                    return
    finally:
        if owned_producer is not None:
            await owned_producer.stop()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await run_relay(settings=settings, should_stop=stop_event.is_set)


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    def request_stop(signum: int, _frame: Any) -> None:
        LOGGER.info("outbox relay received signal=%s", signal.Signals(signum).name)
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, request_stop)
        except (AttributeError, ValueError):
            continue


def _postgres_connection_factory(settings: Settings) -> Callable[[], Any]:
    def connect() -> Any:
        import psycopg

        return psycopg.connect(settings.database_url)

    return connect


def _default_producer_kwargs(settings: Settings) -> dict[str, Any]:
    """Translate typed settings into aiokafka's security options.

    Local replay/T153 settings intentionally remain PLAINTEXT.  Production
    settings are validated before this function can return SASL_SSL options.
    """

    kwargs: dict[str, Any] = {
        "bootstrap_servers": settings.redpanda_brokers,
    }
    if settings.redpanda_security_protocol == "PLAINTEXT":
        return kwargs
    kwargs["security_protocol"] = settings.redpanda_security_protocol
    if settings.redpanda_security_protocol.startswith("SASL"):
        kwargs["sasl_mechanism"] = settings.redpanda_sasl_mechanism
        kwargs["sasl_plain_username"] = settings.redpanda_sasl_username
        password = settings.redpanda_sasl_password
        if password is None and settings.redpanda_sasl_password_file:
            password = (
                Path(settings.redpanda_sasl_password_file).read_text(encoding="utf-8").strip()
            )
        if not password:
            raise RuntimeError("Redpanda SASL password is unavailable")
        kwargs["sasl_plain_password"] = password
    if settings.redpanda_security_protocol.endswith("SSL"):
        kwargs["ssl_cafile"] = settings.redpanda_tls_ca_file
        if settings.redpanda_tls_cert_file:
            kwargs["ssl_certfile"] = settings.redpanda_tls_cert_file
        if settings.redpanda_tls_key_file:
            kwargs["ssl_keyfile"] = settings.redpanda_tls_key_file
    return kwargs


def _default_producer_factory(**kwargs: Any) -> Any:
    from aiokafka import AIOKafkaProducer

    return AIOKafkaProducer(**kwargs)


if __name__ == "__main__":
    asyncio.run(main())
