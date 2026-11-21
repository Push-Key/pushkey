# Pushkey Production External Gate Operator Runbook

Status: 2026-07-22 operator runbook.

This runbook is the step-by-step companion for the remaining hosted evidence
and credential gates. It is intentionally operational rather than aspirational:
do not advance to the next step until the current step has a real artifact,
service record, or operator acknowledgment.

Use this runbook together with:

- [production-external-gate-handoff-checklist.md](production-external-gate-handoff-checklist.md)
- [production-rollback-backup-infrastructure-checklist.md](production-rollback-backup-infrastructure-checklist.md)
- [production-rollback-drill-results.template.json](production-rollback-drill-results.template.json)
- [release-readiness.md](release-readiness.md)
- [REMAINING_TO_100_PERCENT_TASKLIST.md](REMAINING_TO_100_PERCENT_TASKLIST.md)
- [ops-readiness.md](ops-readiness.md)

## What This Runbook Covers

The remaining external finish line is:

- hosted PostgreSQL backups and point-in-time recovery;
- versioned object-storage backups;
- destructive restore evidence;
- production rollback evidence;
- signing credentials and signed-install verification;
- independent security review and penetration testing;
- final release sign-off.

## Do Not Use Local Evidence As A Substitute

The following are useful inputs, but they do not close the external gates:

- local alpha rollback and capacity results;
- local-only snapshot tests;
- branch-protection screenshots without a live release record;
- unsigned artifacts with checksums only;
- placeholder alert destinations;
- documentation without hosted provider, backup, or restore records.

## Evidence Matrix

Collect the following evidence in the matching document.

### 1. `production-rollback-backup-infrastructure-checklist.md`

Use this document to prove the hosted backup and restore infrastructure exists.

Record these exact fields:

- managed PostgreSQL provider name and environment identifier;
- versioned object-storage provider name and bucket or container identifier;
- production deployment target for `pushkey_cloud_api.py`;
- production-like staging environment identifier;
- backup automation for PostgreSQL;
- backup or versioning policy for object storage;
- monitoring and alerting coverage for auth, sync, activation, storage, email,
  rate limits, and backup age;
- live operator routing destinations for alerts;
- point-in-time recovery or equivalent restoreable snapshot;
- version history restore for object-storage blobs;
- documented rollback path from the last known good release tag or commit;
- documented restore path that recovers metadata and encrypted blobs together;
- accountable operator ownership for deploys, alerts, backup health, incident
  response, and signing credentials.

Mark the checklist complete only when each unchecked item has a real hosted
artifact or record attached.

### 2. `production-rollback-drill-results.template.json`

Use this file as the canonical record for destructive restore and rollback
drills.

Fill in these exact fields:

- `generated_at`
- `verification_scope`
- `environment.provider`
- `environment.region`
- `environment.service`
- `environment.deployment_commit`
- `backup.database_snapshot_id`
- `backup.object_storage_version_id`
- `backup.backup_timestamp`
- `backup.retention_policy`
- `rollback.bad_deploy_commit`
- `rollback.rolled_back_to`
- `rollback.rollback_timestamp`
- `rollback.rollback_result`
- `restore.restore_type`
- `restore.restore_timestamp`
- `restore.restored_metadata`
- `restore.restored_encrypted_blobs`
- `restore.record_count_check`
- `restore.hash_reconciliation`
- `smoke_tests`
- `alerts.operator`
- `alerts.delivery_proof`
- `alerts.delivery_blocker`
- `rpo_seconds`
- `rto_seconds`
- `residual_risk`

Use one JSON file per hosted drill attempt. Do not reuse alpha-local drill data
for production claims.

### 3. `ops-readiness.md`

Use this document only for live monitoring and alert-delivery proof.

Record these exact fields:

- dashboard screenshot or export;
- metric names;
- observation window;
- alert thresholds;
- uptime or latency snapshot;
- live mailbox or incident-tool destination;
- alert message ID;
- delivery timestamp;
- acknowledgement timestamp;
- operator owner;
- SMTP acceptance;
- IMAP receipt.

Do not mark monitoring complete unless the proof is tied to a live operator
destination and a real delivery event.

### 4. `release-readiness.md`

Use this document for signing, signed artifacts, and final release sign-off.

Record these exact fields:

- release tag;
- commit SHA;
- artifact names;
- SHA-256 checksum file;
- issuer or CA;
- certificate fingerprint;
- expiry;
- signing key storage location;
- platform coverage;
- artifact signing workflow;
- sample signing command or build log;
- name or role of each signer;
- known issues accepted;
- date and time of sign-off.

Treat code signing, notarization, and signed-install verification as Public
Beta gates, not Alpha gates.

### 5. `REMAINING_TO_100_PERCENT_TASKLIST.md`

Use this document for the external security review and penetration test.

Record these exact fields:

- reviewer identity;
- scope;
- report date;
- test window;
- report artifact;
- retest results;
- findings summary;
- explicit coverage of cloud API, admin, portal, local API, browser
  extension, VS Code extension, and sync;
- final signoff or mitigation owner.

Keep critical/high findings open until the retest artifact exists and the issue
is explicitly closed.

## Step-By-Step Sequence

### Step 1. Confirm Baseline

Confirm that these repo-local gates are already closed before you start the
hosted work:

- branch protection and release gates;
- alpha packaging and checksum publication;
- production monitoring and alert delivery.

If any of those are missing, stop and restore the missing evidence first.

### Step 2. Provision Hosted Storage

Provision the hosted PostgreSQL and object-storage services.

Then update `production-rollback-backup-infrastructure-checklist.md` with:

- provider names;
- environment identifiers;
- bucket or container names;
- deployment target;
- staging mirror identifier;
- backup policy;
- versioning policy;
- alert routing destinations.

Stop when the checklist has hosted provider records and backup automation
details, not just a plan.

### Step 3. Record Backup And Restore Inputs

Take the first production backup or snapshot after the hosted services are
ready.

Capture:

- backup ID or snapshot ID;
- backup timestamp;
- retention policy;
- object-storage version ID or equivalent immutable reference;
- deployment commit or release tag that the backup protects.

Put those values into `production-rollback-backup-infrastructure-checklist.md`
and prep the matching JSON drill record.

### Step 4. Run The Destructive Restore Drill

Perform a restore that starts from the production backup or PITR point and
proves the restored metadata and encrypted blobs are usable.

Capture in `production-rollback-drill-results.template.json`:

- the restore type;
- the restore timestamp;
- the backup or PITR source;
- the restored commit or release tag;
- record count reconciliation;
- hash reconciliation;
- smoke tests for health, admin login, activation, and vault/blob access;
- measured RPO and RTO;
- residual risk.

Update the handoff checklist only after the JSON record exists and the smoke
tests pass.

### Step 5. Run The Production Rollback Drill

Simulate a bad deploy or bad state mutation, then roll back to the last known
good release or commit.

Capture in `production-rollback-drill-results.template.json`:

- bad deploy commit or tag;
- rollback target commit or tag;
- rollback start and end timestamps;
- rollback result;
- user impact summary;
- post-rollback smoke tests.

The rollback drill is not complete until the post-rollback smoke tests pass and
the rollback evidence is attached.

### Step 6. Refresh Monitoring Evidence If Needed

If the monitoring or alerting environment changed, refresh the live monitoring
proof in `ops-readiness.md`.

Do not redo this step if the existing evidence is still current and attached.

### Step 7. Acquire Signing Credentials And Produce Signed Artifacts

Obtain the Windows signing credentials and macOS notarization/signing access.

Then update `release-readiness.md` with:

- issuer or CA;
- certificate fingerprint;
- expiry;
- signing key storage location;
- platform coverage;
- artifact signing workflow;
- sample signing command or build log;
- release tag;
- commit SHA;
- artifact names;
- checksum file;
- signer names or roles;
- known issues accepted;
- sign-off timestamp.

Do not mark signing complete until the signed artifacts and checksum record are
both attached.

### Step 8. Verify Install, Upgrade, And Rollback

On each claimed platform, verify that the signed artifacts install cleanly and
that upgrade/rollback behavior is still correct.

Record the verification outcome in `release-readiness.md` and keep the final
sign-off record up to date.

Minimum fields to capture:

- platform and architecture;
- clean-room or fresh-machine identifier;
- install command;
- signature or checksum verification output;
- install result;
- upgrade result;
- rollback result;
- any platform-specific caveats.

### Step 9. Commission Independent Security Review

Provide the external reviewer with the current codebase, release scope, and the
security questions to answer.

Capture in `REMAINING_TO_100_PERCENT_TASKLIST.md`:

- reviewer identity;
- scope;
- test window;
- report artifact;
- findings summary;
- retest results;
- signoff status.

### Step 10. Run Penetration Testing

Make sure the test scope explicitly covers:

- cloud API;
- admin API;
- portal;
- local API;
- browser extension;
- VS Code extension;
- sync path.

Attach the pentest report artifact and keep any critical/high findings open
until retest proves closure.

### Step 11. Final Release Sign-Off

Only after every hosted evidence record and external credential gate is in
place, update the release sign-off records and close the remaining boxes.

Before marking anything complete, confirm:

- the handoff checklist has links to the evidence artifacts;
- the backup/restore checklist has real hosted provider and snapshot data;
- the drill JSON record has the actual restore and rollback values;
- the release-readiness record has the signing and install data;
- the remaining-task list has the review and pentest evidence;
- the roadmap tracker still reflects the current state.

## Stop Conditions

Stop immediately if any of the following are true:

- you only have a screenshot but not the underlying hosted record;
- the record still points at alpha-local evidence;
- the signing credential is missing or not approved for release use;
- the reviewer has not returned a report artifact;
- the restore or rollback smoke test failed;
- the evidence fields do not match the doc you are filling.

If you stop, leave the related checklist item unchecked and note the blocker
explicitly.
