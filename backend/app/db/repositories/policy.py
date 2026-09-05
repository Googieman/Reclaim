"""Backward-compatible import path for the authoritative policy repositories."""

from .policies import PolicyDecisionRepository, PolicyVersionRepository

__all__ = ["PolicyDecisionRepository", "PolicyVersionRepository"]
