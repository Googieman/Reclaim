"""Versioned contracts for bounded, advisory documentation help."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HelpStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNAVAILABLE = "unavailable"


class HelpChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    case_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class HelpSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=300)


class HelpChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: HelpStatus
    answer: str | None = None
    sources: tuple[HelpSourceReference, ...] = ()
    model_profile: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    request_id: str = Field(min_length=1)


class HelpGatewayRequest(BaseModel):
    """Only reviewed passages and the bounded question cross the help boundary."""

    model_config = ConfigDict(extra="forbid")

    profile: str = Field(default="reclaim-help-deepseek", pattern=r"^reclaim-help-deepseek$")
    question: str = Field(min_length=1, max_length=2_000)
    passages: tuple[str, ...] = Field(max_length=8)
    max_output_tokens: int = Field(default=1_024, ge=1, le=1_024)


class HelpGatewayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_text: str | None = Field(default=None, max_length=12_000)
    source_ids: tuple[str, ...] = Field(max_length=8)
    model_revision: str = Field(min_length=1, max_length=200)
    token_count: int | None = Field(default=None, ge=0)


__all__ = [
    "HelpChatRequest",
    "HelpChatResponse",
    "HelpGatewayRequest",
    "HelpGatewayResponse",
    "HelpSourceReference",
    "HelpStatus",
]
