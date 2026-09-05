# Razorpay Test Mode action seam

RECLAIM validates payment-action proposals against an explicitly supplied,
authoritative merchant-side payment record before any adapter call. A refund
requires a captured payment, a positive integer minor-unit amount no larger than
the unreimbursed amount, an explicit currency, and the original payment source.
Request fields, model metadata, and arbitrary refund destinations cannot
establish those facts.

The adapter is a Test Mode/replay seam only. Live financial execution is disabled
by default and the current adapter has no HTTP client. A future live implementation
would require separately configured policy, Action Gateway credentials, an exact
approval, Test Mode provider configuration, reconciliation, and post-action
verification before it could be considered for activation.

The Action Gateway accepts only tenant-bound action controls and simulator-mode
manifests in this release. Tenant connector/action allowlists, bounded parameter
and amount limits, the emergency disable switch, and the action circuit breaker
are checked before connector invocation. Missing controls, an unqualified/live
manifest, or either live-action setting fails closed. Deterministic replay
fixtures remain labeled `replay`; no fixture or static check qualifies live
merchant execution.
