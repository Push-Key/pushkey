# Pushkey Production External Gate Handoff Checklist

Status date: 2026-07-24

This document is the operator handoff for the remaining production-only gates.
It is intentionally external-first: each item needs a real artifact, service
record, screenshot, or operator acknowledgment before it can be marked
complete.

The step-by-step execution companion lives in
[production-external-gate-operator-runbook.md](production-external-gate-operator-runbook.md).

## Repo-Local Actions Completed

- [x] Re-ran `scripts/alpha_capacity_smoke.py --users 16 --iterations 8 --output docs/alpha-capacity-load-results.json --max-p95-ms 1000` and preserved the JSON result.
- [x] Updated `docs/90_PERCENT_EXECUTION_CHECKLIST.md` to `320/327` and closed the last local Track A load-test slice.
- [x] Updated `docs/90_PERCENT_LOCAL_EXECUTION_QUEUE.md` to point at this handoff checklist.
- [x] Added this handoff checklist with evidence fields for every external production gate.
- [x] Linked this checklist from `docs/release-readiness.md` and `docs/ops-readiness.md`.
- [x] Refreshed the stale progress snapshots in `docs/100_PERCENT_COMPLETION_TASKLIST.md`, `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`, and `docs/alpha-launch-boundary-note.md`.
- [x] Verified `scripts/roadmap_progress.py --json` reports `320/327` for the alpha-launch bucket.
- [x] Ran `pytest tests/test_readiness_checklists.py tests/test_ops_readiness_docs.py -q`.
- [x] Confirmed no stale `304/337`, `307/337`, `308/337`, `90.2%`, `91.1%`, or `91.4%` references remain in the repo docs.
- [x] Verified `git diff --check` is clean apart from existing line-ending warnings in unrelated files.
- [x] Closed the "no release can be cut from an unverified commit" gate with an
  executable in-pipeline control (`verify-provenance` job in
  `.github/workflows/release.yml` running
  `scripts/verify_release_commit_provenance.py`) and re-verified live: the
  2026-07-24 `scripts/verify_release_branch_protection.py` run returns **PASS**
  (`docs/release-branch-protection-verification-results.json`).
- [x] Drafted the redundant tag ruleset in `docs/release-tag-ruleset.json` with
  `scripts/apply_release_tag_ruleset.py`, which stays dry-run until an operator
  approves the repository-admin change.
- [x] Closed the WCAG 2.2 AA gate: nine critical journeys scanned by axe-core
  pass with zero violations on Chromium, Firefox, and WebKit; four contrast/ARIA
  defects fixed; the scan now runs in the required `Local web app build` CI job.
  Record: `docs/accessibility-conformance.md`.
- [x] Repaired `web-app/package-lock.json`, which was out of sync with
  `package.json` and would have failed every `npm ci` step in CI.
- [x] Cleared the `npm audit --audit-level=high` failure in both frontends by
  overriding the transitive `sharp` dependency to `^0.35.3`
  (GHSA-f88m-g3jw-g9cj); `next@16.2.11` still pins the vulnerable `sharp@0.34.5`
  upstream. Both `web` and `web-app` now report zero high findings.

Current verified local state:

- `docs/alpha-capacity-results.json` records the baseline alpha smoke.
- `docs/alpha-capacity-load-results.json` records the beta and launch
  concurrency load test.
- Live operator mailbox delivery proof has been captured and cross-referenced
  in the alpha sellable readiness checklist.
- GitHub `main` has an active ruleset with pull-request review and
  no-fast-forward protection, plus classic branch protection with required CI
  checks and required pull-request review.
- The protected `release` environment is configured with required reviewers.
- The public `v0.1.0-alpha` release tag is published.
- `docs/production-rollback-backup-infrastructure-checklist.md` captures the
  hosted backup and restore prerequisites.
- `docs/production-external-gate-operator-runbook.md` is the execution
  companion for collecting the hosted evidence, signing records, and external
  review artifacts.

## Alpha Launch Actions (Do These First)

These four gate inviting real users. Everything else in this document is
deferred to Public Beta or GA and is not blocking alpha.

| Status | Action | Notes |
|---|---|---|
| [ ] | Push the branch, open the PR, get CI green on the release commit | `main` requires review. This is also what proves the accessibility gate, release provenance gate, and dependency fixes run in CI. |
| [ ] | Turn on managed database backups in the hosting provider console | Settings toggle. Record provider, schedule, and retention below. |
| [ ] | Add an external uptime check on the cloud API health endpoint | Free tier is fine. Alert delivery to the accountable operator is already proven; this is what fires it. |
| [ ] | Cut a new alpha tag containing the vault write-loss fix | The published `v0.1.0-alpha` binaries predate the fix and silently discard the second of two rapid key edits. Do not invite testers onto that build. |

## Handoff Rules

- Do not mark a gate complete from documentation alone.
- Attach the external evidence in the cited doc or operator record before
  changing the checkbox.
- Keep placeholder destinations, unsigned artifacts, and simulated drills in
  the not-complete state.
- Treat code signing, artifact signing, and signed-install verification as
  deferred Public Beta gates, not Alpha blockers.

## Remaining Production / Public Beta Gates

Everything in this table is deferred past alpha. Each item needs money, hosted
infrastructure, or a paid third party, and none of it can be closed from the
repository. Deferring is a scheduling decision: nothing here was lowered or
marked complete to move a percentage, and all of it stays counted in the
tracker's `public_beta_gate` bucket.

The checklist below is ordered by the current production / Public Beta
sequence. Code signing stays last and remains a deferred risk for invite-only
Alpha.

| Status | Gate | Evidence fields | Primary record |
|---|---|---|---|
| [ ] | Encrypted PostgreSQL backups and restore strategy | database provider; backup schedule; retention policy; PITR window; snapshot ID; successful restore timestamp | `docs/production-rollback-backup-infrastructure-checklist.md` |
| [ ] | Object-storage backup/versioning strategy | bucket or container; versioning policy; retention policy; object version ID; restore proof. Supabase Storage does not support native S3 versioning, so this gate requires an immutable backup pattern or a different object-storage provider. | `docs/production-rollback-backup-infrastructure-checklist.md` |
| [x] | Production monitoring and alert delivery | dashboard screenshot or export; metric names; observation window; alert thresholds; uptime or latency snapshot; live mailbox or incident-tool destination; alert message ID; delivery timestamp; acknowledgement timestamp; operator owner; SMTP acceptance; IMAP receipt | `docs/ops-readiness.md` |
| [ ] | Destructive restore drill | restore start and end timestamps; source snapshot or PITR ID; restored commit or release tag; record reconciliation; smoke-test results; RPO/RTO | `docs/production-rollback-drill-results.template.json` |
| [ ] | Production rollback drill | bad deploy identifier; rollback target SHA or tag; start and end timestamps; user impact; success outcome; post-rollback smoke tests | `docs/production-rollback-drill-results.template.json` |
| [x] | Main-branch protection and release gates | branch-protection screenshot or API export; required checks list; merge policy; release-gate settings; immutable release controls | `docs/release-readiness.md` |
| [x] | Release commit provenance | live `gh api` verdict; workflow job graph; required check contexts. Closed in-pipeline, not by repository settings. Applying the drafted tag ruleset (`scripts/apply_release_tag_ruleset.py --apply`) as a redundant second layer is still an open **operator decision**, not a blocker. | `docs/release-branch-protection-verification-results.json` |
| [x] | Alpha packaging and checksum publication | release tag; commit SHA; artifact names; SHA-256 checksum file; official distribution channel; tester-warning copy | `docs/release-readiness.md` |
| [ ] | Independent security review | reviewer identity; scope; report date; findings summary; retest or signoff status | `docs/REMAINING_TO_100_PERCENT_TASKLIST.md` |
| [ ] | Penetration testing before Public Beta | tester identity; scope; test window; report artifact; retest results; explicit coverage of cloud API, admin, portal, local API, extensions, and sync | `docs/REMAINING_TO_100_PERCENT_TASKLIST.md` |
| [ ] | Code signing before Public Beta | Deferred. Accepted risk for invite-only Alpha. Required before Public Beta or commercial launch. issuer or CA; certificate fingerprint; expiry; signing key storage location; platform coverage; artifact signing workflow; sample signing command or build log | `docs/release-readiness.md` |

## Deferred Future Gates

- `Signed-artifact install confirmation` remains a Public Beta gate and is
  tracked in `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`.
- `Critical/high findings resolved` remains a later GA gate and is tracked in
  `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`.

## Handoff Notes

- The alert aliases in `docs/ops-readiness.md` now point at the verified live
  operator mailbox destinations.
- The public `v0.1.0-alpha` release tag now includes the official alpha
  binary/checksum bundle, so the packaging gate is closed for invite-only
  Alpha.
- GitHub main-branch protection and release-gate settings are now configured
  and recorded in the release-readiness evidence.
- The backup and rollback infrastructure checklist stays separate because it
  needs hosted environment evidence, not local proof.
- Local load testing is already complete; the remaining blockers are external
  by design.
- Alpha packaging and checksum publication must stay on official distribution
  channels with explicit tester warnings and release metadata.
