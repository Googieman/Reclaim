"""Unit tests for tenant context and transaction ownership."""

from __future__ import annotations

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
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


def authorization_context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="service-test",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id, required_role="service")


def test_tenant_context_rejects_blank_and_sets_transaction_local_setting() -> None:
    connection = FakeConnection()
    auth_context = authorization_context()
    with pytest.raises(TenantContextError, match="tenant_id"):
        TenantContext(tenant_id=" ", authorization_context=auth_context)

    context = TenantContext.from_authorization_context(auth_context)
    context.apply(connection)
    assert connection.calls == [("SELECT set_config('reclaim.tenant_id', %s, true)", ("tenant-a",))]


def test_unit_of_work_commits_authoritative_transaction() -> None:
    connection = FakeConnection()
    with PostgresUnitOfWork(
        lambda: connection, authorization_context=authorization_context()
    ) as unit_of_work:
        assert unit_of_work.tenant_context.tenant_id == "tenant-a"
        assert unit_of_work.authorization_context.tenant_id == "tenant-a"
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
        with PostgresUnitOfWork(lambda: connection, authorization_context=authorization_context()):
            raise RuntimeError("abort")

    assert connection.rolled_back
    assert not connection.committed
    assert connection.closed


def test_tenant_context_rejects_tenant_override_against_authenticated_context() -> None:
    with pytest.raises(TenantContextError, match="authenticated authorization"):
        TenantContext(tenant_id="tenant-b", authorization_context=authorization_context("tenant-a"))


def test_unit_of_work_requires_authenticated_authorization_context() -> None:
    connection = FakeConnection()
    with pytest.raises(TypeError):
        PostgresUnitOfWork(lambda: connection)  # type: ignore[call-arg]


def test_unit_of_work_rejects_caller_tenant_override() -> None:
    connection = FakeConnection()
    with pytest.raises(TypeError):
        PostgresUnitOfWork(
            lambda: connection,
            authorization_context=authorization_context(),
            tenant_id="tenant-b",  # type: ignore[call-arg]
        )
