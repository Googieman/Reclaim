"""Typed, side-effect-free tools exposed to the bounded analysis harness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.security.boundaries import AllowedCapability, CapabilityViolation

from .redaction import redact_value

TOOL_SCHEMA_VERSION = "tools-v1.0.0"

_PROPOSAL_ACTIONS = frozenset({"revoke_suspicious_session", "hold_fulfillment"})
_FORBIDDEN_OPERATION_PARTS = frozenset(
    {
        "account",
        "attacker",
        "cancel",
        "credential",
        "database",
        "execute",
        "financial",
        "network",
        "payment",
        "probe",
        "refund",
        "restore",
        "shell",
    }
)


class ToolBoundaryError(CapabilityViolation):
    """A typed tool request could not be safely dispatched."""


class UnknownToolError(ToolBoundaryError):
    """The model requested a tool outside the fixed registry."""


class ToolArgumentError(ToolBoundaryError):
    """A registered tool received an unsupported argument shape."""


class CrossTenantToolError(ToolBoundaryError):
    """A tool request attempted to leave its tenant/case binding."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Provider-neutral tool-call envelope after strict boundary decoding."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]
    schema_version: str = TOOL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("call_id", "name", "schema_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ToolArgumentError(f"tool call {name} is required")
        if self.schema_version != TOOL_SCHEMA_VERSION:
            raise ToolArgumentError("unsupported tool call schema version")
        if not isinstance(self.arguments, Mapping):
            raise ToolArgumentError("tool call arguments must be an object")
        object.__setattr__(self, "arguments", dict(self.arguments))


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Typed result returned to a model provider; it contains no capability handle."""

    call_id: str
    name: str
    tenant_id: str
    case_id: str
    ok: bool
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    schema_version: str = TOOL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("call_id", "name", "tenant_id", "case_id", "schema_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ToolArgumentError(f"tool result {name} is required")
        if self.schema_version != TOOL_SCHEMA_VERSION:
            raise ToolArgumentError("unsupported tool result schema version")
        object.__setattr__(self, "output", dict(redact_value(self.output)))


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Read-only case data explicitly supplied by the trusted caller."""

    tenant_id: str
    case_id: str
    case_representation: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("tenant_id", "case_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ToolArgumentError(f"tool context {name} is required")
        object.__setattr__(self, "case_representation", redact_value(self.case_representation))
        object.__setattr__(self, "evidence", redact_value(self.evidence))


@dataclass(frozen=True, slots=True)
class AdvisoryProposalInput:
    """Non-executable proposal-interface output owned by a later parser/policy stage."""

    tenant_id: str
    case_id: str
    action_type: str
    target_resource: str
    rationale: str
    evidence_references: tuple[str, ...]
    attribution_references: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("tenant_id", "case_id", "action_type", "target_resource", "rationale"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ToolArgumentError(f"proposal interface {name} is required")
        if self.action_type not in _PROPOSAL_ACTIONS:
            raise ToolArgumentError("proposal action is not allowlisted at this boundary")
        _references(self.evidence_references, "evidence_references")
        _references(self.attribution_references, "attribution_references")
        object.__setattr__(
            self,
            "evidence_references",
            tuple(sorted(set(self.evidence_references))),
        )
        object.__setattr__(
            self,
            "attribution_references",
            tuple(sorted(set(self.attribution_references))),
        )
        object.__setattr__(self, "parameters", redact_value(self.parameters))


class ReadCaseTool:
    name = AllowedCapability.READ_CASE.value

    def __init__(self, context: ToolContext) -> None:
        self.context = context

    def invoke(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        _exact_keys(arguments, set(), self.name)
        return dict(self.context.case_representation)


class ReadEvidenceTool:
    name = AllowedCapability.READ_EVIDENCE.value

    def __init__(self, context: ToolContext) -> None:
        self.context = context

    def invoke(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        _exact_keys(arguments, {"evidence_id"}, self.name)
        evidence_id = arguments["evidence_id"]
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ToolArgumentError("read_evidence evidence_id is required")
        try:
            value = self.context.evidence[evidence_id]
        except KeyError as exc:
            raise ToolArgumentError("evidence reference is not present in the request") from exc
        return dict(redact_value(value))


class ProposalInterfaceTool:
    """Capture a bounded advisory intent without creating, validating, or executing a proposal."""

    name = AllowedCapability.PROPOSE_ACTION.value

    def __init__(self, context: ToolContext) -> None:
        self.context = context

    def invoke(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed = {
            "action_type",
            "target_resource",
            "rationale",
            "evidence_references",
            "attribution_references",
            "parameters",
        }
        _exact_keys(
            arguments,
            allowed,
            self.name,
            required={"action_type", "target_resource", "rationale", "evidence_references"},
        )
        action_type = arguments.get("action_type")
        if not isinstance(action_type, str) or _is_forbidden_operation(action_type):
            raise ToolBoundaryError("forbidden or unsupported operation in proposal interface")
        evidence_references = _references(
            arguments.get("evidence_references", ()), "evidence_references"
        )
        if not set(evidence_references).issubset(set(self.context.evidence)):
            raise ToolArgumentError("proposal references evidence not present in the request")
        result = AdvisoryProposalInput(
            tenant_id=self.context.tenant_id,
            case_id=self.context.case_id,
            action_type=action_type,
            target_resource=_required_text(arguments.get("target_resource"), "target_resource"),
            rationale=_required_text(arguments.get("rationale"), "rationale"),
            evidence_references=evidence_references,
            attribution_references=_references(
                arguments.get("attribution_references", ()), "attribution_references"
            ),
            parameters=_mapping(arguments.get("parameters", {}), "parameters"),
        )
        return {
            "status": "advisory_only",
            "executable": False,
            "proposal_input": {
                "tenant_id": result.tenant_id,
                "case_id": result.case_id,
                "action_type": result.action_type,
                "target_resource": result.target_resource,
                "rationale": result.rationale,
                "evidence_references": list(result.evidence_references),
                "attribution_references": list(result.attribution_references),
                "parameters": dict(result.parameters),
            },
        }


class ToolRegistry:
    """Fixed registry for the only capabilities available to the model."""

    _FACTORIES = {
        AllowedCapability.READ_CASE.value: ReadCaseTool,
        AllowedCapability.READ_EVIDENCE.value: ReadEvidenceTool,
        AllowedCapability.PROPOSE_ACTION.value: ProposalInterfaceTool,
    }

    def __init__(
        self,
        context: ToolContext | None = None,
        *,
        allowed_tools: Sequence[str] | None = None,
    ) -> None:
        self.context = context
        declared = tuple(allowed_tools) if allowed_tools is not None else tuple(self._FACTORIES)
        if len(set(declared)) != len(declared):
            raise ToolArgumentError("tool registry entries must be unique")
        unknown = set(declared) - set(self._FACTORIES)
        if unknown:
            raise UnknownToolError(f"unknown model tools: {sorted(unknown)}")
        self._allowed_tools = frozenset(declared)

    @classmethod
    def for_request(cls, request: Any, *, context: ToolContext | None = None) -> ToolRegistry:
        if context is not None and (
            request.tenant_id != context.tenant_id or request.case_id != context.case_id
        ):
            raise CrossTenantToolError("tool context does not match analysis request")
        return cls(context, allowed_tools=request.allowed_tools)

    def names(self) -> frozenset[str]:
        return self._allowed_tools

    def require(self, name: str | AllowedCapability) -> None:
        normalized = name.value if isinstance(name, AllowedCapability) else name
        if normalized not in self._allowed_tools:
            if normalized in _FORBIDDEN_OPERATION_PARTS:
                raise CapabilityViolation(f"forbidden model capability: {normalized}")
            raise UnknownToolError(f"model tool is not available: {normalized}")

    def invoke(self, call: ToolCall) -> ToolResult:
        if not isinstance(call, ToolCall):
            raise ToolArgumentError("tool invocation must use the typed ToolCall envelope")
        self.require(call.name)
        if self.context is None:
            raise ToolArgumentError("tool registry requires a bound read-only context")
        _check_scope_arguments(call.arguments, self.context)
        tool = self._FACTORIES[call.name](self.context)
        output = tool.invoke(call.arguments)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            tenant_id=self.context.tenant_id,
            case_id=self.context.case_id,
            ok=True,
            output=output,
        )

    execute = invoke


FixedToolRegistry = ToolRegistry
AgentToolRegistry = ToolRegistry


def _check_scope_arguments(arguments: Mapping[str, Any], context: ToolContext) -> None:
    for key in ("tenant_id", "case_id"):
        value = arguments.get(key)
        if value is not None and value != getattr(context, key):
            raise CrossTenantToolError(f"tool argument {key} does not match its binding")


def _exact_keys(
    arguments: Mapping[str, Any],
    allowed: set[str],
    tool: str,
    *,
    required: set[str] | None = None,
) -> None:
    if not isinstance(arguments, Mapping):
        raise ToolArgumentError(f"{tool} arguments must be an object")
    unknown = set(arguments) - allowed
    missing = (required if required is not None else allowed) - set(arguments)
    if unknown or missing:
        raise ToolArgumentError(
            f"{tool} arguments do not match schema; missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _is_forbidden_operation(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_")
    return normalized not in _PROPOSAL_ACTIONS or any(
        part in normalized for part in _FORBIDDEN_OPERATION_PARTS
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ToolArgumentError(f"{name} must be an object")
    return value


def _references(value: object, name: str) -> tuple[str, ...]:
    if value is None or isinstance(value, str | bytes):
        raise ToolArgumentError(f"{name} must be a sequence")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ToolArgumentError(f"{name} must be a sequence") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ToolArgumentError(f"{name} contains an invalid reference")
    return tuple(item.strip() for item in values)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError(f"{name} is required")
    return value.strip()


__all__ = [
    "AdvisoryProposalInput",
    "AgentToolRegistry",
    "CrossTenantToolError",
    "FixedToolRegistry",
    "ProposalInterfaceTool",
    "ReadCaseTool",
    "ReadEvidenceTool",
    "TOOL_SCHEMA_VERSION",
    "ToolArgumentError",
    "ToolBoundaryError",
    "ToolCall",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "UnknownToolError",
]
