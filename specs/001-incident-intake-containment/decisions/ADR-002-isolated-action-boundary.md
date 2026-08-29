# ADR-002: Isolated Action Gateway and Bounded Model Authority

**Status**: Accepted for FS-001 planning
**Date**: 2026-08-30

## Context

Incident analysis may recommend containment, but financial, account, and merchant-system mutations are high impact. Evidence and model output are untrusted, and uncertain remote outcomes must not cause duplicate effects.

## Decision

The model receives redacted structured evidence and typed read/proposal interfaces only. It has no side-effect credentials, arbitrary network access, shell access, database-write authority, or direct connector access. Typed proposals pass deterministic validation and immutable versioned policy, required independent approval, and stable idempotency before entering the isolated Action Gateway. The gateway alone invokes allowlisted merchant-controlled actions, reconciles unknown results before retry, verifies resulting state, and records verified success, verified failure, or escalation.

## Consequences

Proposal schemas, policy versions, approvals, connector manifests, gateway state, verification evidence, and audit records are first-class contracts. Some model recommendations will be denied or escalated even when plausible. Live financial execution remains disabled by default.

## Rejected alternatives

Direct model tools, API-route bypasses, shared broad credentials, automatic refunds without approval, and treating timeout as failure/success were rejected by the constitution and financial-safety requirements.
