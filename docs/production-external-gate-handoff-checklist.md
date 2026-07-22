# Pushkey Production External Gate Handoff Checklist

Status date: 2026-07-22

This document is the operator handoff for the remaining production-only gates.
It is intentionally external-first: each item needs a real artifact, service
record, screenshot, or operator acknowledgment before it can be marked
complete.

## Repo-Local Actions Completed

- [x] Re-ran `scripts/alpha_capacity_smoke.py --users 16 --iterations 8 --output docs/alpha-capacity-load-results.json --max-p95-ms 1000` and preserved the JSON result.
- [x] Updated `docs/90_PERCENT_EXECUTION_CHECKLIST.md` to `307/337` and closed the last local Track A load-test slice.
- [x] Updated `docs/90_PERCENT_LOCAL_EXECUTION_QUEUE.md` to point at this handoff checklist.
- [x] Added this handoff checklist with evidence fields for every external production gate.
- [x] Linked this checklist from `docs/release-readiness.md` and `docs/ops-readiness.md`.
- [x] Refreshed the stale progress snapshots in `docs/100_PERCENT_COMPLETION_TASKLIST.md`, `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`, and `docs/alpha-launch-boundary-note.md`.
- [x] Verified `scripts/roadmap_progress.py --json` still reports `307/337`.
- [x] Ran `pytest tests/test_readiness_checklists.py tests/test_ops_readiness_docs.py -q`.
- [x] Confirmed no stale `304/337` or `90.2%` references remain in the repo docs.
- [x] Verified `git diff --check` is clean apart from existing line-ending warnings in unrelated files.

Current verified local state:

- `docs/alpha-capacity-results.json` records the baseline alpha smoke.
- `docs/alpha-capacity-load-results.json` records the beta and launch
  concurrency load test.
- `docs/production-rollback-backup-infrastructure-checklist.md` captures the
  hosted backup and restore prerequisites.

## Handoff Rules

- Do not mark a gate complete from documentation alone.
- Attach the external evidence in the cited doc or operator record before
  changing the checkbox.
- Keep placeholder destinations, unsigned artifacts, and simulated drills in
  the not-complete state.
- Treat code signing, artifact signing, and signed-install verification as
  deferred Public Beta gates, not Alpha blockers.

## Alpha External Readiness Priorities

The checklist below is ordered by the current Alpha priority sequence. Code
signing stays last and remains a deferred risk for invite-only Alpha.

| Status | Gate | Evidence fields | Primary record |
|---|---|---|---|
| [ ] | Encrypted PostgreSQL backups and restore strategy | database provider; backup schedule; retention policy; PITR window; snapshot ID; successful restore timestamp | `docs/production-rollback-backup-infrastructure-checklist.md` |
| [ ] | Object-storage backup/versioning strategy | bucket or container; versioning policy; retention policy; object version ID; restore proof. Supabase Storage does not support native S3 versioning, so this gate requires an immutable backup pattern or a different object-storage provider. | `docs/production-rollback-backup-infrastructure-checklist.md` |
| [ ] | Production monitoring and alert delivery | dashboard screenshot or export; metric names; observation window; alert thresholds; uptime or latency snapshot; live mailbox or incident-tool destination; alert message ID; delivery timestamp; acknowledgement timestamp; operator owner | `docs/ops-readiness.md` |
| [ ] | Destructive restore drill | restore start and end timestamps; source snapshot or PITR ID; restored commit or release tag; record reconciliation; smoke-test results; RPO/RTO | `docs/production-rollback-drill-results.template.json` |
| [ ] | Production rollback drill | bad deploy identifier; rollback target SHA or tag; start and end timestamps; user impact; success outcome; post-rollback smoke tests | `docs/production-rollback-drill-results.template.json` |
| [ ] | Main-branch protection and release gates | branch-protection screenshot or API export; required checks list; merge policy; release-gate settings; immutable release controls | `docs/release-readiness.md` |
| [ ] | Alpha packaging and checksum publication | release tag; commit SHA; artifact names; SHA-256 checksum file; official distribution channel; tester-warning copy | `docs/release-readiness.md` |
| [ ] | Independent security review | reviewer identity; scope; report date; findings summary; retest or signoff status | `docs/REMAINING_TO_100_PERCENT_TASKLIST.md` |
| [ ] | Penetration testing before Public Beta | tester identity; scope; test window; report artifact; retest results; explicit coverage of cloud API, admin, portal, local API, extensions, and sync | `docs/REMAINING_TO_100_PERCENT_TASKLIST.md` |
| [ ] | Code signing before Public Beta | Deferred. Accepted risk for invite-only Alpha. Required before Public Beta or commercial launch. issuer or CA; certificate fingerprint; expiry; signing key storage location; platform coverage; artifact signing workflow; sample signing command or build log | `docs/release-readiness.md` |

## Deferred Future Gates

- `Signed-artifact install confirmation` remains a Public Beta gate and is
  tracked in `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`.
- `Critical/high findings resolved` remains a later GA gate and is tracked in
  `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`.

## Handoff Notes

- The alert aliases in `docs/ops-readiness.md` are still placeholders until a
  live mailbox or incident tool is recorded.
- The backup and rollback infrastructure checklist stays separate because it
  needs hosted environment evidence, not local proof.
- Local load testing is already complete; the remaining blockers are external
  by design.
- Alpha packaging and checksum publication must stay on official distribution
  channels with explicit tester warnings and release metadata.
