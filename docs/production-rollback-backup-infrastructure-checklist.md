# Production Rollback And Backup Infrastructure Checklist

Date: 2026-07-21

This checklist defines the infrastructure required before a **production**
rollback drill and backup evidence can be claimed.

Current truth as of 2026-07-21:

- Local alpha rollback and capacity evidence exist in
  `docs/alpha-rollback-drill-results.json` and
  `docs/alpha-capacity-load-results.json`.
- Those local artifacts do not satisfy production backup/PITR, versioned
  object-storage restore, destructive restore, or live alert-delivery proof.
- Alert delivery is still blocked by the placeholder `ops-primary@push-key.com`
  and `ops-secondary@push-key.com` aliases in `docs/ops-readiness.md`; no live
  mailbox or incident-tool destination has been recorded.

## 1. Services To Provision

- [ ] Managed PostgreSQL instance for production metadata.
- [ ] Versioned object storage bucket for encrypted vault blobs.
- [ ] Production deployment of `pushkey_cloud_api.py` pointing at the hosted
  PostgreSQL and object storage services.
- [ ] Production-like staging environment that mirrors the hosted backend.
- [ ] Backup automation for PostgreSQL.
- [ ] Backup/versioning policy for object storage.
- [ ] Monitoring and alerting for auth, sync, activation, storage, email, rate
  limits, and backup age.
- [ ] Live operator routing destinations for alerts.

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
- [ ] Alert-delivery proof for the accountable operator, captured from a live
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

## 5. Not Enough

The following are not sufficient by themselves:

- alpha encrypted-blob rollback results;
- local alpha capacity load results;
- local-only snapshot tests;
- documentation without a real hosted backup or restore record;
- placeholder alert destinations.
