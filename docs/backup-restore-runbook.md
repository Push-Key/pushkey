# Pushkey Backup, Restore, Rollback, And Key Rotation Runbook

Status: Phase 10 operations draft.

This runbook covers the promoted production storage mode and preserves the
local alpha encrypted-blob evidence path below for reference. The production
mode requires hosted PostgreSQL metadata plus versioned object-storage blobs.
For the infrastructure required before a real production backup/PITR,
versioned restore, destructive restore, or rollback drill, see
[production-rollback-backup-infrastructure-checklist.md](production-rollback-backup-infrastructure-checklist.md).

## Verified Local Evidence

Recorded on 2026-07-21:

- Local alpha destructive restore / rollback drill:
  [alpha-rollback-drill-results.json](alpha-rollback-drill-results.json)
- Local alpha capacity smoke evidence:
  [alpha-capacity-load-results.json](alpha-capacity-load-results.json)
- Local cloud storage migration smoke:
  [cloud-storage-migration-results.json](cloud-storage-migration-results.json)
- Alert delivery proof: captured in the accountable operator inbox via SMTP
  acceptance and IMAP receipt.

## Promoted Production Storage Mode

Production storage mode is the hosted PostgreSQL plus versioned object-storage
path that replaces the alpha encrypted-blob-only mode once the infrastructure
and drill evidence exist.

Every production backup record must include:

- storage mode: `production-postgresql-object-storage`
- backup ID and production commit or release tag
- PostgreSQL snapshot or PITR identifier
- object-storage bucket/container and version ID or object key
- encrypted vault blob count and aggregate SHA-256 hash
- metadata and blob reconciliation output
- operator, start time, completion time, and storage location
- restore smoke result for health, admin login, activation, vault/blob access,
  and alert delivery

For hosted production drills, record the same categories in
`docs/production-rollback-drill-results.template.json` and attach the live
backup/PITR, rollback, restore, and alert-delivery proof to the release record.
Operator-narrative evidence templates for backup/PITR, destructive restore,
and rollback drills live in `docs/evidence-templates/`.

## Local Alpha Storage Mode

Alpha uses the single-machine encrypted-blob cloud mode documented in
`docs/release-readiness.md`: account/license metadata and encrypted vault
revisions remain on the application volume until the PostgreSQL/object-storage
migration is promoted for GA. Cloud sync is limited to opt-in encrypted backup
beta. Operators must not market this mode as durable multi-device production
sync. The local procedures below are evidence for alpha only and do not prove
hosted PostgreSQL point-in-time recovery or versioned object-storage restores.

Every alpha backup record must include:

- storage mode: `alpha-encrypted-blob`
- backup ID and application commit
- encrypted vault blob count and aggregate SHA-256 hash
- account/license metadata file checksums
- operator, start time, completion time, and storage location
- restore smoke result for health, license activation, admin login, and
  encrypted backup beta read/write

## Backup Procedure

- Snapshot the application data directory daily until PostgreSQL migration is
  complete.
- Store encrypted vault blob backups separately from application logs.
- Keep signing keys, admin bootstrap credentials, SMTP credentials, and release
  tokens in the platform secret store.
- Record backup start time, completion time, operator, storage location, and
  checksum where available.

## Restore Procedure

1. Freeze writes or put the affected service in maintenance mode.
2. Preserve the damaged data directory or database snapshot for investigation.
3. Restore the newest backup that satisfies the target RPO.
4. Reconcile record counts and encrypted blob hashes.
5. Run smoke tests for health, license activation, admin login, and support
   ticket reads. For alpha, also run encrypted backup beta upload/download
   smoke against the restored alpha volume. This is local validation only, not
   hosted PITR or versioned object-storage proof.
6. Record RPO/RTO, operator, backup ID, restored commit, and residual risk.

### Production Destructive Restore Drill Tooling

`scripts/production_restore_drill.py` implements the destructive-restore
drill for the promoted production storage mode: it seeds vault/license/ticket
data, deletes and corrupts the vault metadata rows and encrypted blob for a
seeded account, restores them from a captured backup, and verifies health,
vault/blob access, activation, support tickets, and admin login. It defaults
to an isolated local/test fixture and accepts `--target-db-url` (PostgreSQL
metadata store) and `--target-object-store-url` (recorded for forward
compatibility; blob storage is still local-disk only in
`pushkey_cloud_api.py`) to point at a hosted staging/production target once
access exists. It writes evidence to
`docs/production-restore-drill-results.json` in the same shape as
`alpha-rollback-drill-results.json`. This script is execution-ready but has
**not** been run against real hosted production infrastructure — the
destructive restore drill item in the roadmap remains open pending hosted
PostgreSQL/object-storage access. See
`docs/production-rollback-backup-infrastructure-checklist.md`.

## Rollback Procedure

1. Stop new deployments.
2. Identify the last known good release tag and artifact checksums.
3. Roll back application code before data migrations unless the migration plan
   states otherwise.
4. Verify health, admin login, activation, heartbeat, and support endpoints.
5. Record rollback reason, affected users, and follow-up owner.

### Production Rollback Drill Tooling

`scripts/production_rollback_drill.py` implements the deployment rollback
drill for the promoted production storage mode: it seeds vault/license/ticket
data under a good release configuration, simulates a bad deploy that breaks
active sessions via a signing-key misconfiguration, rolls the application
configuration back to the last known good release, and verifies health, the
previously broken session, login, activation/heartbeat, support tickets, and
admin login all recover with no data loss. It defaults to an isolated
local/test fixture and accepts the same `--target-db-url` and
`--target-object-store-url` flags as the restore drill to point at a hosted
staging/production target once access exists. It writes evidence to
`docs/production-rollback-drill-results.json`. This script is
execution-ready but has **not** been run against real hosted production
infrastructure — the production rollback drill item in the roadmap remains
open pending hosted PostgreSQL/object-storage access. See
`docs/production-rollback-backup-infrastructure-checklist.md`.

## Incident Procedure

1. Assign an incident owner and severity.
2. Preserve logs and audit records.
3. Disable compromised admin accounts and revoke sessions.
4. Rotate affected platform, signing, SMTP, and release credentials.
5. Communicate user impact using the support/security policy template.
6. Complete a post-incident review with root cause, timeline, and corrective
   actions.

## Key-Rotation Procedure

- Rotate admin bootstrap and break-glass credentials after any use.
- Rotate JWT signing keys according to the signing-key rotation plan.
- Rotate package/release tokens after maintainer changes or suspected exposure.
- Rotate SMTP and object-storage credentials after incident response or provider
  key-age threshold.
