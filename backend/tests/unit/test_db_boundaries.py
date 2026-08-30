"""Unit tests for tenant context and transaction ownership."""

from __future__ import annotations

import pytest

from app.db.tenant_context import TenantContext, TenantContextError
from app.db.unit_of_work import PostgresUnitOfWork


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, query: str, params: object = ()) -> None:
        self.calls.append((query, params))

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_tenant_context_rejects_blank_and_sets_transaction_local_setting() -> None:
    connection = FakeConnection()
    with pytest.raises(TenantContextError, match="tenant_id"):
        TenantContext(" ")

    context = TenantContext(" tenant-a ")
    context.apply(connection)
    assert connection.calls == [
        ("SELECT set_config('reclaim.tenant_id', %s, true)", ("tenant-a",))
    ]


def test_unit_of_work_commits_authoritative_transaction() -> None:
    connection = FakeConnection()
    with PostgresUnitOfWork(lambda: connection, tenant_id="tenant-a") as unit_of_work:
        assert unit_of_work.tenant_context.tenant_id == "tenant-a"
        assert unit_of_work.connection is connection
        assert unit_of_work.tenants is not None

    assert connection.calls[0] == ("BEGIN", ())
    assert connection.calls[1] == (
        "SELECT set_config('reclaim.tenant_id', %s, true)",
        ("tenant-a",),
    )
    assert connection.committed
    assert not connection.rolled_back
    assert connection.closed


def test_unit_of_work_rolls_back_on_error() -> None:
    connection = FakeConnection()
    with pytest.raises(RuntimeError, match="abort"):
        with PostgresUnitOfWork(lambda: connection, tenant_id="tenant-a"):
            raise RuntimeError("abort")

    assert connection.rolled_back
    assert not connection.committed
    assert connection.closed
