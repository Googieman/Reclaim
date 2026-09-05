from __future__ import annotations

from dataclasses import dataclass

from app.help_chat.retrieval import DocumentationRetriever
from app.help_chat.service import HelpChatService
from packages.contracts.help_chat import HelpGatewayRequest, HelpGatewayResponse, HelpStatus


@dataclass
class FakeGateway:
    response: HelpGatewayResponse
    calls: list[HelpGatewayRequest]

    def complete(self, request: HelpGatewayRequest) -> HelpGatewayResponse:
        self.calls.append(request)
        return self.response


def _service(response: HelpGatewayResponse) -> tuple[HelpChatService, FakeGateway]:
    gateway = FakeGateway(response, [])
    return (
        HelpChatService(
            retriever=DocumentationRetriever.from_default_index(),
            gateway=gateway,
        ),
        gateway,
    )


def test_supported_documentation_question_returns_only_allowlisted_sources() -> None:
    service, gateway = _service(
        HelpGatewayResponse(
            final_text="Use the intake API and verify the original webhook payload.",
            source_ids=("intake.webhook-verification",),
            model_revision="test-model",
            token_count=19,
        )
    )

    result = service.answer("How do I verify a webhook?")

    assert result.status is HelpStatus.ANSWERED
    assert result.answer
    assert [source.source_id for source in result.sources] == ["intake.webhook-verification"]
    assert result.model_profile == "reclaim-help-deepseek"
    assert len(gateway.calls) == 1
    assert gateway.calls[0].profile == "reclaim-help-deepseek"


def test_unsupported_question_abstains_without_calling_the_model() -> None:
    service, gateway = _service(
        HelpGatewayResponse(
            final_text="should not be used",
            source_ids=("unknown",),
            model_revision="x",
        )
    )

    result = service.answer("What is the weather on Mars today?")

    assert result.status is HelpStatus.INSUFFICIENT_EVIDENCE
    assert result.answer is None
    assert not gateway.calls


def test_malformed_or_uncited_model_output_is_unavailable() -> None:
    service, _ = _service(
        HelpGatewayResponse(
            final_text="<think>private reasoning</think>",
            source_ids=("intake.webhook-verification",),
            model_revision="test-model",
        )
    )

    result = service.answer("How do I verify a webhook?")

    assert result.status is HelpStatus.UNAVAILABLE
    assert result.answer is None


def test_gateway_timeout_is_an_explicit_unavailable_result() -> None:
    class TimeoutGateway:
        def complete(self, request: HelpGatewayRequest) -> HelpGatewayResponse:
            raise TimeoutError("test timeout")

    service = HelpChatService(
        retriever=DocumentationRetriever.from_default_index(), gateway=TimeoutGateway()
    )

    result = service.answer("How do I verify a webhook?")

    assert result.status is HelpStatus.UNAVAILABLE
    assert result.answer is None
