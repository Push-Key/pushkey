# Pushkey Remaining Task List To 100 Percent

Status date: 2026-07-22

Current measured readiness:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py --json
```

Current result: 307/337 production items complete, 91.1%.
90% target: 307/337 production items complete.
100% target: 337/337 production items complete plus 3/3 post-alpha review items.

This document is the consecutive execution queue from the current verified
state to full GA readiness. It intentionally separates locally finishable work
from external proof gates such as signing credentials, production infrastructure,
branch protection, independent review, and penetration testing.

## Completion Rules

- Do not check off an item without code, tests, CI output, artifact validation,
  operator/security/legal documentation, or an external evidence record.
- Do not count signing, penetration testing, independent review, branch
  protection, or production monitoring as complete until the real external
  artifact exists.
- Keep alpha claims constrained to the release scope in
  `docs/release-readiness.md`.
- Treat signing, signed-install verification, and clean-machine installation as
  Public Beta gates, not Alpha blockers.
- Run the roadmap tracker after every completed slice and record the new result.

Verification after every slice:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py --json
git diff --check
git status --short
```

## Phase 1, Reconcile Progress Records And Reach 90 Percent

Goal: remove stale checklist contradictions and close the fastest verified
local items needed to reach 307/337.

- [x] Update stale measured-readiness snapshots in
  `docs/100_PERCENT_COMPLETION_TASKLIST.md` to match the roadmap tracker.
- [x] Reconcile `docs/90_PERCENT_EXECUTION_CHECKLIST.md` with already-completed
  alpha UI, Playwright, admin, and packaging evidence from
  `docs/100_PERCENT_COMPLETION_TASKLIST.md`.
- [x] Reconcile `docs/ALPHA_SELLABLE_READINESS_CHECKLIST.md` sync-scope items
  with the selected alpha sync position in `docs/release-readiness.md`.
- [x] Verify zero-knowledge properties at API responses, logs, database
  metadata, migration state, export paths, and object-storage abstraction.
- [x] Run and record beta/launch concurrency load-test evidence beyond the
  alpha smoke threshold in `docs/alpha-capacity-load-results.json`.
- [ ] Confirm alert routing reaches the accountable operator and record the
  delivery proof.
- [x] Record checksum verification behavior separately from signature
  verification so unsigned alpha artifacts are not falsely claimed as signed.

Exit gate:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

The production result is at least 307/337, or the remaining blockers are listed
with exact reasons they cannot be completed locally.

## Phase 2, Finish Alpha Go/No-Go

Goal: make paid/evaluation alpha launchable without overstating GA readiness.

- [ ] Ensure every alpha blocker in
  `docs/ALPHA_SELLABLE_READINESS_CHECKLIST.md` is checked or explicitly removed
  from alpha scope.
- [ ] Re-run the full Python test suite.
- [ ] Re-run both frontend lint/build pipelines.
- [x] Re-run web-app Playwright coverage for local vault journeys.
- [x] Re-run web/admin portal coverage for license, support, audit, MFA,
  session, and role journeys.
- [ ] Re-run package/install smoke tests from clean temp homes.
- [ ] Record the alpha launch decision, known limitations, and accepted risks in
  a dated readiness note.

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web-app run lint
npm --prefix web-app run build
npm --prefix web run lint
npm --prefix web run build
```

Exit gate: alpha launch is go/no-go documented, with no unchecked alpha blocker
left unexplained.

## Phase 3, Production Storage And Sync Migration

Goal: replace alpha flat-file cloud storage with durable production storage.

- [x] Migrate encrypted vault blobs to versioned object storage.
- [x] Store vault revision metadata transactionally in PostgreSQL.
- [x] Remove production flat-file write paths after migration.
- [x] Add migration scripts, rollback scripts, and idempotency safeguards.
- [x] Add tests proving encrypted blobs remain opaque to the API, logs,
  database rows, object metadata, and exports.
- [x] Add restore tests covering database metadata plus object-storage blobs.
- [x] Update `docs/backup-restore-runbook.md` from alpha-encrypted-blob mode
  to the promoted production storage mode.

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cloud_vault_sync.py tests\test_cloud_migrations.py -q
```

Exit gate: production cloud writes no longer depend on flat-file storage, and a
restore drill can recover metadata and encrypted blobs together.

## Phase 4, Distributed Controls And Production Operations

Goal: prove the deployed service remains safe under horizontal scaling and
operational failure.

- [x] Add distributed rate limiting through Redis, API gateway policy, or an
  equivalent production control plane.
- [x] Prove rate limits, lockouts, idempotency, and abuse controls cannot be
  bypassed by restart or horizontal scaling.
- [ ] Configure encrypted database backups and point-in-time recovery.
- [ ] Configure versioned object-storage backups.
- [ ] Conduct and record a destructive restore drill.
- [ ] Run and record a production rollback drill.
- [ ] Obtain production monitoring evidence for health, auth, sync, activation,
  email, storage, rate limits, and alerting.
- [ ] Confirm alerts page or notify the accountable operator during a real drill.

Exit gate: production operations evidence exists outside local docs, including
backup, restore, rollback, monitoring, and alert-delivery records.

## Phase 5, Public Beta Signing And Supply Chain Gates

Goal: make released artifacts trustworthy and non-bypassable for Public Beta
and beyond.

These gates are intentionally deferred from Alpha. Alpha may ship unsigned with
checksums and release metadata, but Public Beta cannot.

- [ ] Acquire and configure Windows signing credentials.
- [ ] Acquire and configure macOS signing/notarization credentials.
- [ ] Sign Windows artifacts.
- [ ] Sign macOS artifacts.
- [ ] Verify signatures and checksums before installation.
- [ ] Confirm signed artifacts install successfully on supported platforms.
- [ ] Prove CI/release cannot bypass tests, scans, signing, approval, or checksum
  publication.
- [ ] Re-run the full test, build, scan, packaging, and install matrix.
- [ ] Conduct clean-room installation on each supported platform.
- [ ] Test upgrade from the latest public version.
- [ ] Test rollback without vault or cloud data loss.

Exit gate: every Public Beta artifact has checksum and signature evidence, and
the release process requires the gates before publication.

## Phase 6, Repository And Release Governance

Goal: make the production branch and release process enforce the documented
standards.

- [ ] Protect the main branch.
- [ ] Require CI, tests, scans, and release approval before merge.
- [ ] Require signed or otherwise verified release artifacts before publication.
- [ ] Record GitHub branch-protection settings via screenshot, API output, or
  repository settings export.
- [ ] Confirm no release can be cut from an unverified commit.
- [ ] Update `docs/release-readiness.md` with the release-candidate SHA,
  artifact checksum file, known issues, and sign-off owners.

Exit gate: repository settings enforce the release process rather than relying
on manual discipline.

## Phase 7, Independent Security Review And Penetration Test

Goal: close the post-alpha external review track.

- [ ] Commission independent crypto/application security review.
- [ ] Penetration-test cloud API, admin portal, public portal, local API, MCP
  integration, extensions, and sync.
- [ ] Resolve all critical and high findings.
- [ ] Triage medium and low findings with owners and deadlines.
- [ ] Fix release-blocking beta defects.
- [ ] Record zero open critical/high security findings.
- [ ] Obtain final engineering, security, operations, product, and legal
  sign-off.

Exit gate:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py --json
```

The result is 337/337 production items and 3/3 post-alpha review items, with
external review, pentest, and final sign-off evidence attached or referenced.

## Recommended Consecutive Motion

1. Complete Phase 1 first. This should be the fastest path from 89.6% to 90%
   because it focuses on reconciliation and local evidence.
2. Complete Phase 2 before inviting paid/evaluation alpha users.
3. Run alpha with constrained claims while collecting defects and support data.
4. Complete Phases 3 and 4 to replace alpha infrastructure with GA
   infrastructure.
5. Complete Phase 5 before inviting Public Beta users or publishing signed
   release artifacts.
6. Complete Phase 6 before public release.
7. Complete Phase 7 before claiming full production/GA readiness.

## Current Known External Blockers

- Public Beta signing credentials, artifact signing, signature verification,
  and signed-install confirmation.
- Production PostgreSQL and object-storage configuration.
- Production Redis/API-gateway or equivalent distributed controls.
- GitHub branch-protection settings access.
- Independent security reviewer.
- Penetration-test provider or internal red-team evidence.
- Final cross-functional sign-off owners.
