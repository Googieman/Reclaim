# Action Gateway Contract

## Request

Required fields: tenant/case/proposal identity, allowlisted connector and operation, bounded target/parameters, policy decision/version, approval reference when required, stable idempotency key, correlation/causation IDs, and request checksum.

## State machine

`received -> validated -> pending_remote -> completed | failed | unknown -> reconciling -> completed | failed | escalated -> verifying -> verified_success | verified_failure | escalated`.

`unknown` cannot transition to a new remote attempt until reconciliation determines the remote state or policy explicitly escalates. A duplicate idempotency key returns the existing execution state and does not issue a second non-idempotent request.

## Response and audit

Return gateway execution identity, connector result class, remote reference where available, idempotency state, reconciliation state, verification requirement, and audit reference. Secrets and raw sensitive payment data are not returned to the model or UI beyond approved redaction.
