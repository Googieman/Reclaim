# ADR-001: Authoritative State, Workflow, Event, and Projection Ownership

**Status**: Superseded for orchestration ownership by ADR-004; authority split retained
**Date**: 2026-08-30 (amended 2026-09-03)

## Context

FS-001 spans business state, durable recovery, asynchronous delivery, relationship exploration, raw evidence, and coordination. The constitution requires explicit ownership so a cache, event offset, workflow history, or graph projection cannot silently become the source of truth.

## Decision

PostgreSQL is authoritative for business state, policy, approvals, actions, verification, escalation, audit, and replay/evaluation metadata. Redpanda transports versioned events via transactional outbox/inbox. Neo4j is a rebuildable projection. MinIO stores immutable raw evidence/artifacts. Redis is limited to bounded cache/locks/rate limiting/coordination. Durable orchestration ownership is now defined by ADR-004: n8n owns new executions and Temporal may only drain existing executions.

## Consequences

All services need explicit PostgreSQL repositories and event contracts. Projections can be rebuilt. Workflow recovery cannot bypass business validation. Redis and Redpanda outages require controlled recovery rather than business-state loss.

## Rejected alternatives

Single-process state, Redis-authoritative state, event-log-only business truth, or Neo4j-authoritative relationships would violate the approved architecture and weaken recovery/audit guarantees.
