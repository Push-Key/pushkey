# Pushkey Backup, Restore, Rollback, And Key Rotation Runbook

Status: Phase 10 operations draft.

## Alpha Storage Mode

Alpha uses the single-machine flat-file cloud mode documented in
`docs/release-readiness.md`: account/license metadata, audit JSONL, and
encrypted vault blobs remain on the application volume until the
PostgreSQL/object-storage migration is promoted for GA. Cloud sync is limited
to opt-in encrypted backup beta. Operators must not market this mode as
durable multi-device production sync.

Every alpha backup record must include:

- storage mode: `alpha-flat-file`
- backup ID and application commit
- encrypted vault blob count and aggregate SHA-256 hash
- account/license metadata file checksums
- operator, start time, completion time, and storage location
- restore smoke result for health, license activation, admin login, and
  encrypted backup beta read/write

## Backup Procedure

- Snapshot flat-file cloud metadata daily until PostgreSQL migration is complete.
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
   smoke against the restored flat-file volume.
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
