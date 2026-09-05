# US3 defensive action fixtures

These fixtures describe deterministic replay outcomes for the two allowlisted
merchant-controlled actions:

- `revoke_suspicious_session` through `session-actions`;
- `hold_fulfillment` through `fulfillment-actions`.

The outcome vocabulary is `accepted`, `rejected`, `completed`, `failed`, and
`unknown`. Fixtures contain no credentials, URLs, arbitrary commands, or live
provider data. They are simulator inputs and must remain labeled `replay`.
