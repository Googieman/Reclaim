"""Forbidden model capabilities are rejected before any connector boundary."""

import pytest
from app.security.boundaries import (
    AllowedCapability,
    BoundedToolSet,
    CapabilityViolation,
)


def test_model_has_only_read_and_proposal_capabilities() -> None:
    tools = BoundedToolSet(
        {
            AllowedCapability.READ_CASE,
            AllowedCapability.READ_EVIDENCE,
            AllowedCapability.PROPOSE_ACTION,
        }
    )
    tools.require(AllowedCapability.READ_CASE)
    tools.require(AllowedCapability.PROPOSE_ACTION)
    for forbidden in (
        "database_write",
        "execute_payment",
        "shell_command",
        "arbitrary_network",
        "credential_probe",
    ):
        with pytest.raises(CapabilityViolation):
            tools.require(forbidden)


def test_model_cannot_invent_an_unlisted_capability() -> None:
    with pytest.raises(CapabilityViolation, match="not available"):
        BoundedToolSet({AllowedCapability.READ_CASE}).require("refund_payment")
