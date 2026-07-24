# Production Rollback And Backup Infrastructure Checklist

Date: 2026-07-22

This checklist defines the infrastructure required before a **production**
rollback drill and backup evidence can be claimed.

Use [production-external-gate-operator-runbook.md](production-external-gate-operator-runbook.md)
for the step-by-step execution order and the exact evidence fields to collect.

Current truth as of 2026-07-22:

- Local alpha rollback and capacity evidence exist in
  `docs/alpha-rollback-drill-results.json` and
  `docs/alpha-capacity-load-results.json`.
- Those local artifacts do not satisfy production backup/PITR, versioned
  object-storage restore, or destructive restore.
- Alert delivery proof is captured in `docs/ops-readiness.md` and
  `docs/ALPHA_SELLABLE_READINESS_CHECKLIST.md`; the remaining production work
  is backup/PITR, versioned object-storage restore, and drill evidence.
- The hosted storage layer is now provisioned in Supabase with a production
  bucket and a staging mirror bucket; the project-specific backup schedule and
  retention window still need management-plane verification.

## 0. Provisioned Hosted Records

- Managed PostgreSQL provider: Supabase.
  - Environment ID / project ref: `viehwjyjwuefsqthindb`.
  - Project name: `Push-Key's Project`.
  - Database host: `db.viehwjyjwuefsqthindb.supabase.co`.
  - Pooler host: `aws-1-us-east-1.pooler.supabase.com`.
  - Postgres version: `17.6.1.111`.
- Versioned object-storage provider: Supabase Storage.
  - Production bucket: `pushkey-vault-prod`.
  - Staging mirror bucket: `pushkey-vault-staging`.
  - Access model: private.
  - Provisioned at: `2026-07-22T23:46:01Z`.
- Backup automation: Supabase-managed daily backups and PITR are the platform
  defaults for Pro, Team, and Enterprise projects, but the project-specific
  schedule is not yet readable from the currently available management token.
- Retention policy: documented Supabase default retention is 7 days for Pro
  backups, 14 days for Team, and 30 days for Enterprise. PITR can be set to 7,
  14, or 28 days. The live project setting still needs dashboard/API
  verification.
- Alert routing: primary live accountable-operator mailbox, secondary backup
  accountable-operator mailbox.

## 1. Services To Provision

- [x] Managed PostgreSQL instance for production metadata.
- [x] Versioned object storage bucket for encrypted vault blobs.
- [ ] Production deployment of `pushkey_cloud_api.py` pointing at the hosted
  PostgreSQL and object storage services.
- [ ] Production-like staging environment that mirrors the hosted backend.
- [ ] Backup automation for PostgreSQL.
- [ ] Backup/versioning policy for object storage.
- [x] Monitoring and alerting for auth, sync, activation, storage, email, rate
  limits, and backup age.
- [x] Live operator routing destinations for alerts.

## 2. Required Operational Capabilities

- [ ] Point-in-time recovery or equivalent restoreable snapshot for PostgreSQL,
  proven by a destructive restore drill.
- [ ] Version history restore for object-storage blobs.
- [ ] Documented rollback path from the last known good release tag or commit.
- [ ] Documented restore path that recovers metadata and encrypted blobs
  together.
- [ ] Accountable operator ownership for deploys, alerts, backup health,
  incident response, and signing credentials.

## 3. Evidence To Capture

- [ ] PostgreSQL provider name and environment identifier.
- [ ] Object storage provider name and bucket/container identifier.
- [ ] Backup schedule and retention policy.
- [ ] Backup IDs or snapshot IDs for a successful backup.
- [ ] Backup timestamp and restoration timestamp.
- [ ] Destructive restore timestamp and outcome.
- [ ] Commit SHA or release tag restored.
- [ ] RPO and RTO measurements.
- [ ] Record counts and hash reconciliation output after restore.
- [ ] Smoke-test results for health, admin login, activation, and vault/blob
  access after restore.
- [ ] Rollback result showing a bad deploy was reverted successfully.
- [x] Alert-delivery proof for the accountable operator, captured from a live
  mailbox or incident tool.

## 4. Minimum Drill Sequence

1. Provision PostgreSQL and object storage.
2. Deploy the production service against those hosted dependencies.
3. Take a backup or snapshot.
4. Simulate a bad deploy or bad state mutation.
5. Roll back to the last known good release or commit.
6. Perform a destructive restore of metadata and encrypted blobs from
   backup/PITR.
7. Run smoke tests and record RPO/RTO plus reconciliation output.
8. Save all evidence in the repo or attached operator records.

Suggested record format:

- `docs/production-rollback-drill-results.template.json`
- Operator-narrative templates: `docs/evidence-templates/` (backup, restore
  drill, rollback drill; unfilled until a real drill runs)

## 5. Not Enough

The following are not sufficient by themselves:

- alpha encrypted-blob rollback results;
- local alpha capacity load results;
- local-only snapshot tests;
- documentation without a real hosted backup or restore record;
- placeholder alert destinations.
