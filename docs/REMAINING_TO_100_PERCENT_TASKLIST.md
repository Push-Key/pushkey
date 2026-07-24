# Pushkey Remaining Task List To 100 Percent

Status date: 2026-07-24

Current measured readiness:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py --json
```

Current result: 317/337 production items complete, 94.1%.
90% target: already exceeded.
100% target: 337/337 production items complete plus 3/3 post-alpha review items.

For invite-only alpha, the roadmap is now clear on the alpha side. The
remaining items in this queue are deferred to post-alpha / Public Beta or full
GA work.

This document is the consecutive execution queue from the current verified
state to full GA readiness. It intentionally separates locally finishable work
from external proof gates such as signing credentials, production infrastructure,
branch protection, independent review, and penetration testing.

## Current Ownership

Current verified state:

- 317/337 production items complete, 94.1%.
- 0/3 post-alpha review items complete.
- Alpha blocker is complete.
- GitHub `main` has an active ruleset with pull-request review and
  no-fast-forward protection, plus classic branch protection with required CI
  checks and required pull-request review.
- The protected `release` environment is configured with required reviewers.
- A release cannot be cut from an unverified commit: the `verify-provenance`
  job gates the whole release workflow. Live verdict PASS, 2026-07-24.
- The public `v0.1.0-alpha` release tag is published.
- The local web app meets WCAG 2.2 AA on all nine critical journeys, enforced
  by a required CI check.

No repo-local gate is blocked on you. Two optional hardening decisions are
yours whenever you want them, and neither blocks anything: applying the drafted
release tag ruleset, and commissioning the manual accessibility review. Every
other remaining gate needs hosted credentials, third-party evidence, or a
sign-off only you can give.

### Agent-Executable Next Slices

- [x] [Agent] Capture the GitHub ruleset and release-gate evidence with
  authenticated `gh` CLI calls and attach it to the handoff docs.
- [x] [Agent] Refresh the remaining task list and handoff checklist after each
  closed gate.
- [x] [Agent] Close the release-provenance gate with an executable in-pipeline
  control and re-verify it live. Done 2026-07-24; verdict PASS.
- [x] [Agent] Close the WCAG 2.2 AA gate for critical journeys and enforce the
  scan in CI. Record: `docs/accessibility-conformance.md`.
- [x] [Agent] Repair the CI-breaking `web-app` lockfile desync and the
  `npm audit --audit-level=high` failure in both frontends.
- [x] [Agent] Draft backup / restore / rollback evidence templates and keep
  them aligned with the runbook. Unfilled templates live in
  `docs/evidence-templates/` (`backup-evidence-template.md`,
  `restore-drill-evidence-template.md`, `rollback-drill-evidence-template.md`);
  the underlying external gates stay open until real drill records are
  attached.
- [x] [Agent] Keep `scripts/roadmap_progress.py --json`, the docs, and the test
  assertions synchronized after each slice.

### External Credential / Service Gates

- [ ] [External] Provide hosted PostgreSQL / object-storage access for PITR,
  versioning, restore, and rollback evidence.
- [ ] [External] Provide signing credentials / notarization access for Public
  Beta.
- [ ] [External] Provide an independent security reviewer or pentest record.
- [ ] [External] Decide whether to apply the drafted release tag ruleset
  (`scripts/apply_release_tag_ruleset.py --apply`). This is a
  repository-admin change to shared state. It is redundant with the
  in-pipeline provenance gate, so it is a hardening decision, not a blocker.
- [ ] [External] Commission the manual accessibility review covering the WCAG
  2.2 AA criteria axe-core cannot evaluate, listed in
  `docs/accessibility-conformance.md`.

### Deferred To Public Beta / GA

- [ ] [Deferred] Sign Windows and macOS artifacts.
- [ ] [Deferred] Verify signed artifacts install successfully.
- [ ] [Deferred] Confirm clean-room install / upgrade / rollback on supported
  platforms.
- [ ] [Deferred] Resolve critical/high security findings and obtain final
  sign-off.

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

## Remaining Split

### 1. Alpha Blocker

This is now complete.

- [x] Confirm alert routing reaches the accountable operator and record the
  delivery proof.

### 2. Post-Alpha / Public Beta Blockers

- [ ] Production backup, restore, rollback, monitoring, and alert-delivery
  evidence.
- [ ] Signing credentials, artifact signing, signed-install verification, and
  clean-room installs.
- [ ] Independent security review, penetration testing, and final sign-off.

The detailed phase-by-phase queue below expands the same split into the full
execution plan.

## Phase 1, Reconcile Progress Records And Reach 90 Percent

Goal: remove stale checklist contradictions and close the fastest verified
local items needed to reach 313/337.

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
- [x] Confirm alert routing reaches the accountable operator and record the
  delivery proof.
- [x] Record checksum verification behavior separately from signature
  verification so unsigned alpha artifacts are not falsely claimed as signed.

Exit gate:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

The production result is at least 313/337, or the remaining blockers are listed
with exact reasons they cannot be completed locally.

## Phase 2, Finish Alpha Go/No-Go

Goal: make paid/evaluation alpha launchable without overstating GA readiness.

- [x] Ensure the Alpha Blocker in
  `docs/ALPHA_SELLABLE_READINESS_CHECKLIST.md` is checked or explicitly removed
  from alpha scope.
- [x] Re-run the full Python test suite.
- [x] Re-run both frontend lint/build pipelines.
- [x] Re-run web-app Playwright coverage for local vault journeys.
- [x] Re-run web/admin portal coverage for license, support, audit, MFA,
  session, and role journeys.
- [x] Re-run package/install smoke tests from clean temp homes.
- [x] Record the alpha launch decision, known limitations, and accepted risks in
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

- [x] Protect the main branch.
- [x] Require CI, tests, scans, and release approval before merge.
- [x] Require signed or otherwise verified release artifacts before publication.
- [x] Record GitHub branch-protection settings via API output.
- [x] Confirm no release can be cut from an unverified commit. Live
  `gh api` verification rerun 2026-07-24
  (`scripts/verify_release_branch_protection.py`, evidence in
  `docs/release-branch-protection-verification-results.json`) returns
  **PASS**. The gap was closed with an executable in-pipeline control instead
  of a repository setting: the `verify-provenance` job in
  `.github/workflows/release.yml` runs
  `scripts/verify_release_commit_provenance.py`, which fails the release
  unless the tagged commit is contained in `main` and every required check
  context in `.github/required-release-checks.json` concluded successfully on
  that exact commit. Both other jobs declare `needs: verify-provenance`, so
  nothing is built, signed, or published for an unverified commit, and
  removing the gate requires a reviewed pull request into the protected
  branch. A tag ruleset remains available as a redundant second layer; it is
  drafted in `docs/release-tag-ruleset.json` and stays unapplied because
  creating it is a repository-admin change to shared state.
- [x] Update `docs/release-readiness.md` with the release-candidate SHA,
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

## Detailed Post-Alpha / Public Beta Blockers

- Public Beta signing credentials, artifact signing, signature verification,
  and signed-install confirmation.
- Production PostgreSQL and object-storage configuration.
- Production Redis/API-gateway or equivalent distributed controls.
- GitHub branch-protection settings access.
- Independent security reviewer.
- Penetration-test provider or internal red-team evidence.
- Final cross-functional sign-off owners.
