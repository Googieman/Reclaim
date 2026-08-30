"""Cross-tenant access is rejected at each foundation boundary."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.auth.oidc import OIDCVerifier, TenantAuthorizationError
from app.control_plane.tenant_config import (
    StaticTenantConfigurationSource,
    TenantConfiguration,
    TenantConfigurationBoundary,
)
from app.observability import CorrelationContext


def test_identity_configuration_and_correlation_cannot_cross_tenants() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "issuer",
            "aud": "api",
            "sub": "user-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_ids": ["tenant-a"],
        },
        "key",
        algorithm="HS256",
    )
    verifier = OIDCVerifier(
        issuer="issuer", audience="api", signing_key="key", algorithms=("HS256",)
    )
    with pytest.raises(TenantAuthorizationError):
        verifier.verify(token, tenant_id="tenant-b")

    boundary = TenantConfigurationBoundary(
        StaticTenantConfigurationSource(
            [TenantConfiguration("tenant-a", frozenset(), "policy-1")]
        )
    )
    with pytest.raises(KeyError):
        boundary.get("tenant-b")
    with pytest.raises(ValueError, match="tenant_id"):
        CorrelationContext(tenant_id=" ", correlation_id="corr-1")
