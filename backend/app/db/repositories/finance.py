"""Backward-compatible import for the deterministic exposure repository."""

from .exposure import ExposureRepository, FinancialExposureRepository

__all__ = ["ExposureRepository", "FinancialExposureRepository"]
