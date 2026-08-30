"""Tenant-scoped declarations for the RECLAIM control plane."""

from .registry import (
    ConnectorDeclaration,
    ConnectorRegistry,
    PolicyOwnerRegistry,
    RoleDeclaration,
    RoleRegistry,
)
from .tenant_config import TenantConfiguration, TenantConfigurationBoundary

__all__ = [
    "ConnectorDeclaration",
    "ConnectorRegistry",
    "PolicyOwnerRegistry",
    "RoleDeclaration",
    "RoleRegistry",
    "TenantConfiguration",
    "TenantConfigurationBoundary",
]
