# Production Backup + PITR Evidence Record

> **UNFILLED TEMPLATE.** This file contains no real evidence. The roadmap
> items "Configure encrypted database backups and point-in-time recovery" and
> "Configure versioned object-storage backups" remain incomplete until a real,
> dated backup record is attached. Repo rule: never mark external evidence
> complete without the real artifact.

Aligned with `docs/backup-restore-runbook.md` (Promoted Production Storage
Mode) and `docs/production-rollback-backup-infrastructure-checklist.md`
(section 3, Evidence To Capture).

## Record Identity

- Storage mode: `production-postgresql-object-storage`
- Backup ID: `<backup or snapshot ID>`
- Production commit or release tag: `<SHA or tag>`
- Operator: `<name / mailbox>`
- Start time (UTC): `<ISO 8601>`
- Completion time (UTC): `<ISO 8601>`
- Evidence storage location: `<repo path or operator record>`

## PostgreSQL Backup + PITR Configuration

- Provider and environment ID: `<e.g. Supabase / project ref>`
- Database host: `<host>`
- Backup schedule: `<e.g. daily, managed>`
- Retention window: `<days>`
- PITR enabled: `<yes/no>` — PITR window: `<7/14/28 days or n/a>`
- PostgreSQL snapshot or PITR identifier: `<ID>`
- Command or management-plane output proving the schedule/PITR setting:

```text
<paste command output, API response, or dashboard export reference>
```

## Object-Storage Backup / Versioning

- Provider and bucket/container: `<e.g. Supabase Storage / pushkey-vault-prod>`
- Versioning or immutable-backup pattern: `<policy>`
- Retention policy: `<days / versions>`
- Object version ID or object key for a captured backup: `<ID>`

## Blob Integrity

- Encrypted vault blob count: `<n>`
- Aggregate SHA-256 hash: `<hash>`
- Metadata and blob reconciliation output:

```text
<paste reconciliation output>
```

## Restore Smoke Result

Result of the post-backup restore smoke (health, admin login, activation,
vault/blob access, alert delivery): `<pass/fail + reference>`

## Sign-Off

- Accountable operator: `<name>` — Date: `<date>` — Result: `<accepted/rejected>`
