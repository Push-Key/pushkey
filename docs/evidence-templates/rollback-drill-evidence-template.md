# Production Rollback Drill Evidence Record

> **UNFILLED TEMPLATE.** This file contains no real evidence. The roadmap item
> "Run and record a production rollback drill" remains incomplete until a
> real, dated drill record against hosted infrastructure is attached. Repo
> rule: never mark external evidence complete without the real artifact.

Aligned with `docs/backup-restore-runbook.md` (Rollback Procedure, Production
Rollback Drill Tooling) and
`docs/production-rollback-backup-infrastructure-checklist.md` (sections 3-4).
Machine-readable output belongs in
`docs/production-rollback-drill-results.json` via
`scripts/production_rollback_drill.py`; this record is the operator narrative.

## Drill Identity

- Operator: `<name / mailbox>`
- Drill start (UTC): `<ISO 8601>`
- Drill end (UTC): `<ISO 8601>`
- Target environment: `<hosted staging / production>` (local fixtures do not
  satisfy this gate)

## Trigger

- Bad deploy identifier: `<SHA, tag, or config change that was rolled back>`
- Failure simulated or observed: `<e.g. signing-key misconfiguration breaking
  active sessions>`
- Detection path: `<alert, monitor, or manual observation>`

## Version Transition

- Version rolled back from: `<bad SHA or tag>`
- Version rolled back to (last known good): `<SHA or tag>`
- Artifact checksums of the rollback target verified: `<yes/no + reference>`
- Rollback command/output reference: `<command output or deploy log>`

## Data-Loss Check

- Vault metadata rows before/after: `<counts>`
- Encrypted blob count and aggregate SHA-256 hash before/after: `<n / hash>`
- License, ticket, and session records reconciled: `<pass/fail>`
- Data loss observed: `<none / description>`

## Post-Rollback Verification

- Health `<pass/fail>`, previously broken session recovered `<pass/fail>`,
  login `<pass/fail>`, activation/heartbeat `<pass/fail>`, support tickets
  `<pass/fail>`, admin login `<pass/fail>`
- User impact window: `<start-end, affected users>`

## Alert Delivery Confirmation

- Alert raised during the drill: `<alert name / rule>`
- Message ID: `<ID>` — Delivery timestamp: `<ISO 8601>`
- Delivered to: `<live accountable-operator mailbox / incident tool>`
- Acknowledgement timestamp: `<ISO 8601>`

## Sign-Off

- Accountable operator: `<name>` — Date: `<date>` — Result: `<accepted/rejected>`
- Follow-up owner for residual actions: `<name or none>`
