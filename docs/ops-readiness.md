# Pushkey Operations Readiness

Status: Phase 10 initial operations targets.

## Availability And Latency Targets

- Cloud API availability target: 99.5% during beta, revisited before general
  availability.
- Admin API p95 latency target: under 500 ms for non-reporting endpoints.
- Device activation and heartbeat p95 latency target: under 500 ms.
- Local-first CLI/vault operations must continue without cloud availability
  except for paid entitlement refresh after the documented grace window.

## RPO And RTO

- Operational metadata RPO: 24 hours until PostgreSQL point-in-time recovery is
  configured.
- Encrypted vault blob RPO: 24 hours until versioned object storage is live.
- Cloud API RTO: 4 hours during beta.
- Local vault RTO: user controlled, based on local backups and recovery code.

## Alpha Dashboard Targets

Track at minimum:

- Auth: registration, login, reset, admin login, MFA failure, lockout, and
  session refresh counts.
- Sync: encrypted vault upload/download count, stale `If-Match` conflicts,
  idempotent retry count, 404 no-vault count, and blob size distribution.
- Activation: activation, heartbeat, deactivation, expired-license, revoked
  license, and device-limit outcomes.
- Storage: JSON/JSONL write failures, encrypted vault blob write failures,
  history write failures, backup age, and restore verification age.
- Email: invite/reset/support send success, failure, and dead-letter count.
- Errors: 4xx/5xx response families, route-level error counts, and top failing
  routes.
- Rate-limit: auth, sync, portal, support, activation, and admin limit events.

The alpha dashboard may be implemented in the hosting platform, Grafana,
Datadog, or a log-derived dashboard, but every panel must be traceable to
`GET /api/v1/ops/metrics`, structured request logs, dead letters, or the
platform volume-backup status.

## Alpha Alert Routing

| Alert | Initial threshold | Primary operator | Secondary operator |
|---|---:|---|---|
| Cloud API 5xx rate | 5 in 10 minutes | live accountable-operator mailbox | backup accountable-operator mailbox |
| Auth/admin lockout spike | 5 in 15 minutes | live accountable-operator mailbox | backup accountable-operator mailbox |
| Rate-limit spike | 25 in 15 minutes | live accountable-operator mailbox | backup accountable-operator mailbox |
| Sync write failure | 1 in 10 minutes | live accountable-operator mailbox | backup accountable-operator mailbox |
| Email dead letter | 1 queued item | live accountable-operator mailbox | backup accountable-operator mailbox |
| Backup age | older than 26 hours | live accountable-operator mailbox | backup accountable-operator mailbox |

The live accountable-operator mailbox destinations above are verified. Alert
delivery proof is recorded in
[ALPHA_SELLABLE_READINESS_CHECKLIST.md](ALPHA_SELLABLE_READINESS_CHECKLIST.md).

The remaining external production gates and their evidence fields are tracked
in
[production-external-gate-handoff-checklist.md](production-external-gate-handoff-checklist.md).
Use that checklist to record the live operator destination, alert proof, and
the production monitoring evidence that supports release readiness.

## Provider-Agnostic Alert-Rule Spec (Ready To Apply, Not Yet Deployed)

[production-monitoring-alert-rules.yaml](production-monitoring-alert-rules.yaml)
defines a versioned, provider-agnostic alert-rule spec covering all seven
alpha dashboard signals (health, auth, sync, activation, email, storage, and
rate limits). Each rule records a plain-language condition, severity, the
accountable-operator notify channel, and the evidence required to close that
signal's gate.

This spec is prep work only. It is ready to apply the moment a hosted
monitoring backend (Grafana/Prometheus, Datadog, or similar) is provisioned,
but it is not yet deployed to a live monitoring backend and does not by
itself close the production monitoring evidence gate tracked in
[REMAINING_TO_100_PERCENT_TASKLIST.md](REMAINING_TO_100_PERCENT_TASKLIST.md).

## Telemetry Redaction

Logs, metrics, alerts, dead letters, exports, and dashboard labels must not include plaintext secrets.
This includes request bodies, authorization headers,
cookies, master passwords, recovery codes, MFA recovery codes, license tokens,
agent tokens, backup key values, and encrypted vault blob contents. Allowed
telemetry is limited to route names, status codes, request IDs, coarse result
types, counts, sizes, hashes/ETags, timestamps, and redacted identifiers.

## Retention Note

Audit/event streams in the cloud state store are append-only with no retention
policy yet; retention/pruning is a pre-GA follow-up.

## Backup And Restore

- Flat-file compatibility deployments must use daily platform volume snapshots.
- Phase 4 must replace this with PostgreSQL backups and object-storage
  versioning.
- Restore drills must prove record counts, hash reconciliation, and encrypted
  blob readability.

## Ownership

- One accountable operator must own production deploys, alerts, backup health,
  incident response, and signing credentials before release candidate.
