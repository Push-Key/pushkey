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

## Monitoring Targets

Track at minimum:

- activation success/failure count;
- heartbeat success/failure count;
- admin login failures;
- sync upload/download failures;
- storage write failures;
- rate-limit events;
- email send failures;
- 5xx responses;
- backup age.

## Backup And Restore

- Flat-file compatibility deployments must use daily platform volume snapshots.
- Phase 4 must replace this with PostgreSQL backups and object-storage
  versioning.
- Restore drills must prove record counts, hash reconciliation, and encrypted
  blob readability.

## Ownership

- One accountable operator must own production deploys, alerts, backup health,
  incident response, and signing credentials before release candidate.
