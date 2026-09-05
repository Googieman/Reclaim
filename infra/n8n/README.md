# RECLAIM n8n orchestration boundary

The checked-in workflows are the only n8n workflows used for new incident
processing:

- `incident-analysis-handoff.v1` consumes `incident.accepted` metadata from
  Redpanda and calls allowlisted tenant-scoped RECLAIM APIs for claim, intake
  normalization, typed analysis/policy, and human handoff. A typed analysis with
  `status=completed` is the only path that records the completed `analyze` stage
  and `awaiting_human`; typed `status=unavailable` records
  `requires_attention` with `failure_code=model_unavailable`, and other
  non-completed typed outcomes record `requires_attention` with
  `failure_code=policy_failed`. Replay is never substituted on this path.
- `incident-analysis-error-recovery.v1` records `requires_attention` when a
  provider, API, worker, or model stage fails. It never substitutes a replay
  result.

Every RECLAIM HTTP node in both workflows uses the same bounded retry
configuration: `retryOnFail=true`, `maxTries=3`, and `waitBetweenTries=5000`
milliseconds. These are configured values, not a measured recovery objective.

n8n has no RECLAIM PostgreSQL, MinIO, model-provider, approval, or Action Gateway
credentials. Its PostgreSQL role is limited to the `n8n` schema and its Redis
database is coordination metadata only. The RECLAIM API is the sole business
state boundary.

`bootstrap.ps1` imports these files idempotently using the n8n API. It upserts
the RECLAIM HTTP credential and, when `N8N_KAFKA_CREDENTIAL_DATA_JSON` is
provided, upserts the read-only Kafka credential and wires its ID into the
workflow. Recovery is imported or updated first, then the handoff workflow is
upserted with `settings.errorWorkflow` replaced by the recovery workflow ID
returned from the n8n API.

Normal bootstrap reuses the currently referenced managed credential by its
stable name. Rotation is an explicit staged operation: set
`RECLAIM_N8N_CREDENTIAL_REVISION` to a new non-secret revision and invoke
`bootstrap.ps1 -Rotate -Activate`. The script creates versioned HTTP/Kafka
credentials, rewires both managed workflows, verifies every credential
reference before activation, and never deletes the previous version. Revoke
the old version in n8n only after the verified workflow reads and an operator
smoke test confirm that the new version is active. A failed rotation leaves
the old workflow and credential available for reconciliation; credentials are
never printed or stored in this repository.

n8n `1.121.0` does not expose public-API list/update routes for credentials.
The bootstrap therefore discovers the IDs of these managed credentials from
existing workflow references and creates a credential only when no valid
reference exists; it never attempts `GET /api/v1/credentials`.

Workflow writes are reduced to fields accepted by the pinned public API. Export-
only `pinData`, read-only `active`, and read-only tag values are not submitted,
and activation is posted without an undeclared request body.

The pinned `n8n-nodes-base.kafkaTrigger` implementation reads non-empty
`topic` and `groupId` node parameters. The handoff definition deliberately uses
those exact fields (not legacy `topics` or `consumerGroupId`) so activation can
create its Kafka consumer group.

The handoff trigger also uses `jsonParseMessage=true` and `onlyMessage=true`.
That makes the authoritative event envelope available directly as `$json`, which
is required by the downstream event-type, tenant, case, and idempotency checks.

Every bootstrap run requires `N8N_API_KEY` and `RECLAIM_N8N_SERVICE_TOKEN`.
`-Activate` additionally requires `N8N_KAFKA_CREDENTIAL_DATA_JSON`. Activation
posts the handoff workflow activation request and then re-reads the workflow to
verify `active=true`; it exits non-zero if the activation prerequisites are
missing or the verification read does not confirm activation. Credential values
are never checked into source or echoed by the bootstrap output. Without
`-Activate`, the import remains inactive pending operator verification of the
tenant-scoped service identity and Redpanda ACLs.
