# Destructive Restore Drill Evidence Record

> **UNFILLED TEMPLATE.** This file contains no real evidence. The roadmap item
> "Conduct and record a destructive restore drill" remains incomplete until a
> real, dated drill record against hosted infrastructure is attached. Repo
> rule: never mark external evidence complete without the real artifact.

Aligned with `docs/backup-restore-runbook.md` (Restore Procedure, Production
Destructive Restore Drill Tooling) and
`docs/production-rollback-backup-infrastructure-checklist.md` (sections 3-4).
Machine-readable output belongs in
`docs/production-restore-drill-results.json` via
`scripts/production_restore_drill.py`; this record is the operator narrative.

## Drill Identity

- Storage mode: `production-postgresql-object-storage`
- Operator: `<name / mailbox>`
- Drill start (UTC): `<ISO 8601>`
- Drill end (UTC): `<ISO 8601>`
- Target environment: `<hosted staging / production>` (local fixtures do not
  satisfy this gate)
- `--target-db-url` host used: `<host, credentials redacted>`
- `--target-object-store-url` used: `<value or n/a>`

## Scenario

- Destruction performed: `<what was deleted/corrupted: metadata rows, blobs>`
- Source snapshot or PITR identifier restored from: `<ID>`
- Backup timestamp: `<ISO 8601>`
- Restored commit or release tag: `<SHA or tag>`

## Steps Executed

1. `<freeze writes / maintenance mode — timestamp>`
2. `<preserve damaged state — location>`
3. `<restore command and output reference>`
4. `<reconciliation>`
5. `<smoke tests>`

## RTO / RPO Observed

- RTO observed: `<duration from destruction to verified recovery>`
- RPO observed: `<data-loss window between backup and destruction>`

## Verification

- Record counts before/after: `<counts>`
- Encrypted blob count and aggregate SHA-256 hash after restore: `<n / hash>`
- Verification queries and output (vault metadata rows, license rows, ticket
  rows for the seeded account):

```text
<paste query text and results>
```

- Smoke tests: health `<pass/fail>`, admin login `<pass/fail>`, activation
  `<pass/fail>`, vault/blob access `<pass/fail>`, support tickets `<pass/fail>`

## Residual Risk

`<open issues found during the drill, or none>`

## Sign-Off

- Accountable operator: `<name>` — Date: `<date>` — Result: `<accepted/rejected>`
