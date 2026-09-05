"""Bounded local identities for the non-production localhost demonstration."""

from __future__ import annotations

from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext


class LocalDemoVerifier:
    """Accept only named, tenant-scoped demo principals.

    This adapter is intentionally not a general authentication mechanism.  It
    is enabled only by the local demo profile and gives the UI explicit,
    distinct reviewer/approver/escalation-owner identities so SoD remains
    observable without requiring a Keycloak setup.
    """

    _TOKENS = {
        "demo-reviewer": ("local-demo-reviewer", frozenset({"reviewer"})),
        "demo-approver": ("local-demo-approver", frozenset({"approver"})),
        "demo-escalation-owner": (
            "local-demo-escalation-owner",
            frozenset({"escalation-owner"}),
        ),
        "demo-policy-owner": ("local-demo-policy-owner", frozenset({"policy-owner"})),
    }
    _SERVICE_TOKENS = {
        "demo-n8n-orchestrator": (
            "reclaim-n8n-orchestrator",
            frozenset({RequiredRole.ORCHESTRATOR.value}),
        ),
    }

    def authorize(
        self,
        token: str,
        *,
        tenant_id: str | None = None,
        required_role: RequiredRole | str | None = None,
    ) -> TenantAuthorizationContext:
        service_value = self._SERVICE_TOKENS.get(token)
        if service_value is not None:
            subject, roles = service_value
            context = TenantAuthorizationContext(
                subject=subject,
                tenant_id=tenant_id,
                roles=roles,
                identity_type=IdentityType.SERVICE,
                issuer="local-demo",
            )
            if required_role is not None:
                context.require_role(required_role)
            return context
        value = self._TOKENS.get(token)
        if value is None or not tenant_id or not tenant_id.strip():
            raise PermissionError("local demo identity is not recognized")
        subject, roles = value
        context = TenantAuthorizationContext(
            subject=subject,
            tenant_id=tenant_id,
            roles=roles,
            identity_type=IdentityType.USER,
            issuer="local-demo",
        )
        if required_role is not None:
            context.require_role(required_role)
        return context


__all__ = ["LocalDemoVerifier"]
