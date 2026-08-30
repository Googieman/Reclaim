"""Authenticated incident intake application boundary."""

from .service import IncidentIntakeService, IntakeServiceError

__all__ = ["IncidentIntakeService", "IntakeServiceError"]
