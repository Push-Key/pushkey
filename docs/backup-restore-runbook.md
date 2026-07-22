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
- Alert delivery proof: not available locally. Blocker:
  `docs/ops-readiness.md` still points `ops-primary@push-key.com` and
  `ops-secondary@push-key.com` at placeholder aliases instead of live mailbox
  or incident-tool destinations.

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

## Rollback Procedure

1. Stop new deployments.
2. Identify the last known good release tag and artifact checksums.
3. Roll back application code before data migrations unless the migration plan
   states otherwise.
4. Verify health, admin login, activation, heartbeat, and support endpoints.
5. Record rollback reason, affected users, and follow-up owner.

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
