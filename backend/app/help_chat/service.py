"""Advisory help-chat orchestration with explicit abstention states."""

from __future__ import annotations

import re
from collections.abc import Callable
from time import monotonic
from uuid import uuid4

from packages.contracts.help_chat import (
    HelpChatResponse,
    HelpGatewayRequest,
    HelpGatewayResponse,
    HelpSourceReference,
    HelpStatus,
)

from .retrieval import DocumentationRetriever

HelpAudit = Callable[[dict[str, object]], None]
_PRIVATE_REASONING = re.compile(r"<think\b|</think\b|<analysis\b|</analysis\b", re.IGNORECASE)


class HelpGateway:
    def complete(
        self, request: HelpGatewayRequest
    ) -> HelpGatewayResponse:  # pragma: no cover - protocol seam
        raise NotImplementedError


class HelpChatService:
    def __init__(
        self,
        *,
        retriever: DocumentationRetriever,
        gateway: HelpGateway,
        profile: str = "reclaim-help-deepseek",
        audit: HelpAudit | None = None,
    ) -> None:
        if profile != "reclaim-help-deepseek":
            raise ValueError("help service profile is fixed to reclaim-help-deepseek")
        self.retriever = retriever
        self.gateway = gateway
        self.profile = profile
        self.audit = audit

    def answer(self, question: str, *, case_id: str | None = None) -> HelpChatResponse:
        request_id = "help:" + uuid4().hex
        started = monotonic()
        passages = self.retriever.search(question)
        if not passages:
            result = self._result(
                request_id=request_id,
                status=HelpStatus.INSUFFICIENT_EVIDENCE,
                answer=None,
                sources=(),
                model_revision="not-called",
            )
            self._audit(request_id, question, case_id, result, started)
            return result

        gateway_request = HelpGatewayRequest(
            question=question,
            passages=tuple(passage.prompt_text for passage in passages),
        )
        try:
            response = self.gateway.complete(gateway_request)
            source_map = {passage.source_id: passage for passage in passages}
            if (
                not response.final_text
                or not response.final_text.strip()
                or _PRIVATE_REASONING.search(response.final_text)
                or not response.source_ids
                or any(source_id not in source_map for source_id in response.source_ids)
            ):
                raise ValueError("help model response is missing a safe final answer or citation")
            sources = tuple(
                HelpSourceReference(
                    source_id=source_id,
                    title=source_map[source_id].title,
                    path=source_map[source_id].path,
                )
                for source_id in response.source_ids
            )
            result = self._result(
                request_id=request_id,
                status=HelpStatus.ANSWERED,
                answer=response.final_text.strip(),
                sources=sources,
                model_revision=response.model_revision,
            )
        except Exception:
            result = self._result(
                request_id=request_id,
                status=HelpStatus.UNAVAILABLE,
                answer=None,
                sources=(),
                model_revision="unavailable",
            )
        self._audit(request_id, question, case_id, result, started)
        return result

    def _result(self, **kwargs: object) -> HelpChatResponse:
        return HelpChatResponse(model_profile=self.profile, **kwargs)

    def _audit(
        self,
        request_id: str,
        question: str,
        case_id: str | None,
        result: HelpChatResponse,
        started: float,
    ) -> None:
        if self.audit is None:
            return
        self.audit(
            {
                "request_id": request_id,
                "question_length": len(question),
                "case_context_requested": case_id is not None,
                "document_version": self.retriever.document_version,
                "profile": self.profile,
                "status": result.status.value,
                "latency_ms": round((monotonic() - started) * 1000, 2),
                "source_ids": tuple(source.source_id for source in result.sources),
            }
        )


__all__ = ["HelpChatService", "HelpGateway"]
