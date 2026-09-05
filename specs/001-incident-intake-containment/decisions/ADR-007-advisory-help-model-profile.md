# ADR-007: Separate advisory documentation-help model profile

Date: 2026-09-05

Status: Proposed implementation design; no model resource or deployment is qualified.

## Context

RECLAIM needs a small operator-facing documentation assistant without allowing a
chatbot to become an investigation, credential, or business-action channel. The
existing Fresh Agent profile has different contracts, evidence inputs, and safety
gates. A shared profile would make model-output and permission failures difficult
to attribute and could blur advisory help with case analysis.

## Decision

Use a separate fixed profile, `reclaim-help-deepseek`, behind the existing
authenticated model gateway. The service receives only a bounded question and
reviewed documentation passages. It has no case lookup, database, shell, web,
arbitrary-network, credential, or action tools. The public API is disabled by
default, requires verified tenant-scoped reviewer identity, and rejects case-aware
requests until independent case-read authorization exists.

The candidate runtime is a private, authenticated llama.cpp service using the
manifested external GGUF artifact. The model profile is not an investigator and
cannot satisfy Fresh Agent qualification. Model weights remain outside Git; no
public model port or public Railway domain is allowed. A missing resource returns
an explicit unavailable state rather than replaying an answer or inventing one.

## Consequences

- Help quality and resource measurements are evaluated in `evals/help-chat/` and
  cannot be used as fraud-detection or investigation evidence.
- The investigator remains independently gated by typed proposals, held-out
  evidence, identity, workflow recovery, and T153/T154 release evidence.
- The first release persists no transcript and audits only redacted request
  metadata, profile/document versions, latency, token count when available, and
  terminal status.
- Case-aware help requires a new decision and independent tenant/case-read tests.

## Related decisions

This decision preserves ADR-002's isolated Action Gateway boundary, ADR-004's n8n
orchestration ownership, and ADR-006's private secret-delivery constraints.
