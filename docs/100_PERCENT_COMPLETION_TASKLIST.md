# Pushkey 100 Percent Completion Tasklist

Status date: 2026-07-21

Current measured readiness:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

Current result: 281/337 production items complete, 83.4%.
Post-alpha review track: 0/3.

This tasklist is the execution path from current state to:

1. paid/evaluation alpha readiness;
2. alpha hardening to GA readiness;
3. post-alpha independent review and certification.

## Rules For Completion

- Do not mark an item complete without code, tests, CI, artifact output, a
  recorded command, or an operator/legal/security document.
- Do not count independent review, penetration testing, signing credentials, or
  branch protection as complete until external evidence exists.
- Keep alpha claims constrained to verified behavior.
- Recalculate roadmap progress after each completed slice.

Verification after every slice:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
git diff --check
git status --short
```

## Phase 1, Alpha Product/UI Completion

Goal: make the product safe to sell/evaluate with alpha users without misleading
claims.

- [x] Reconcile every local web app operation with `docs/local-api-v1.md`.
- [x] Complete loading, empty, error, locked, offline, and conflict states.
- [x] Add safe secret reveal/copy timeouts.
- [x] Prove secret values do not enter analytics, browser logs, local storage,
  session storage, screenshots, or persistent app state.
- [x] Add keyboard navigation and focus management for critical journeys.
- [x] Validate supported alpha responsive viewports.
- [x] Remove or disable unimplemented “coming soon” controls.
- [x] Validate all product/admin/website claims against tested capability.
- [x] Configure metadata, canonical URLs, sitemap, robots, Open Graph, and error pages.
- [x] Add CSP-compatible analytics and consent behavior if analytics remains enabled.
- [x] Replace boilerplate `web/README.md` with an operator/developer runbook.

Evidence:

```powershell
npm --prefix web-app run lint
npm --prefix web-app run build
npm --prefix web run lint
npm --prefix web run build
```

Roadmap items expected to close:

- Phase 6 local app/UI checks.
- Phase 6 website/admin claim checks.
- Master “Core local workflows complete” if E2E verifies the flows.

## Phase 2, Alpha E2E And Regression Coverage

Goal: prove critical user journeys work from browser/API boundaries, not just
unit tests.

- [x] Add Playwright coverage for local vault journeys:
  unlock, list, add, rotate, reveal timeout, inject, lock, offline.
- [x] Add portal tests for license lookup, renewal request, support ticket
  creation, and privacy-safe failures.
- [x] Add admin journey tests for license, contact, audit, settings, support,
  MFA, disabled admins, expired sessions, revoked sessions, and role boundaries.
- [ ] Add security regression tests across multiple app instances/workers where
  local execution can simulate it.
- [x] Run the full Python suite.
- [x] Run both frontend lint/build pipelines.
- [x] Run package/install smoke tests from a clean environment.

Evidence:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web-app run lint
npm --prefix web-app run build
npm --prefix web run lint
npm --prefix web run build
.\.venv\Scripts\python.exe -m build --outdir dist\python
```

Roadmap items expected to close:

- Playwright/core vault journey coverage.
- Portal/admin journey coverage.
- Unit/integration/contract/E2E/install gate, only after all listed commands pass.

## Phase 3, Packaging And Installer Completion

Goal: make installation and upgrade predictable for alpha users.

- [x] Make PyInstaller builds reproducible from a clean checkout.
- [x] Verify executable icons and version resources.
- [x] Produce supported alpha OS/architecture artifacts.
- [x] Test upgrade without vault loss.
- [x] Align installer asset names with CI release artifacts.
- [x] Verify checksums before installation.
- [x] Fail with a nonzero exit code on unsuccessful installation.
- [x] Handle unsupported OS/architecture explicitly.
- [x] Document arm64 as supported or unsupported.
- [x] Prevent Windows shim self-resolution loops.
- [x] Test `npm install -g`, `npx`, upgrade, and uninstall in clean environments.
- [x] Fresh-machine smoke tests run `pushkey --help`, `pushkey init`, and
  `pushkey app`.
- [x] Release assets exactly match the npm download map.

Evidence:

```powershell
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe build_exe.py
.\dist\pushkey-cli.exe --help
```

Roadmap items expected to close:

- Reproducible package and binary builds.
- Clean installation on every claimed alpha platform.
- Upgrade and rollback tested where local alpha scope allows.

External dependency:

- Artifact signing remains post-alpha unless signing credentials are available.

## Phase 4, Alpha Operations And Observability

Goal: support real alpha users without losing incident visibility.

- [x] Configure dashboard targets for auth, sync, activation, storage, email,
  errors, rate limits, and alerts.
- [x] Add an operator alert-routing record.
- [x] Run alpha-scale capacity/load test and record results.
- [x] Run alpha rollback drill and record result.
- [ ] Confirm alerts reach an accountable operator.
- [x] Confirm logs, metrics, alerts, dead letters, and exports contain no
  plaintext secrets.
- [x] Record backup/restore procedure for the chosen alpha storage mode.

Evidence:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_admin_api.py tests\test_cloud_vault_sync.py -q
.\.venv\Scripts\python.exe scripts\alpha_capacity_smoke.py --users 8 --iterations 4 --max-p95-ms 750
.\.venv\Scripts\python.exe -m pytest tests\test_alpha_capacity_report.py -q
.\.venv\Scripts\python.exe scripts\alpha_rollback_drill.py
.\.venv\Scripts\python.exe -m pytest tests\test_alpha_rollback_drill_report.py -q
```

Roadmap items expected to close:

- Dashboards/actionable alerts.
- Capacity/load test.
- Rollback drill.
- Logs/telemetry contain no plaintext secrets.
- Monitoring/alerts active for alpha.

## Phase 5, Sync And Storage Decision

Goal: make the alpha sync claim precise.

Choose one:

- [x] Cloud sync enabled for alpha as encrypted-blob sync with documented limits.
- [x] Cloud sync disabled/beta-scoped for alpha, with marketing/onboarding claims removed.

If enabled:

- [x] Document encrypted-blob-only behavior.
- [x] Document conflict behavior and user-facing limitations.
- [x] Add zero-knowledge regression checks for API, logs, database migration
  metadata, and object-storage abstraction.

If disabled:

- [x] Remove sync claims from alpha product and docs.
- [x] Keep cloud sync visible only as beta/internal.

Roadmap items expected to close:

- Sync conflict handling complete, only for the selected alpha scope.
- Deferred features absent from launch claims remains enforced.

## Phase 6, GA Infrastructure Completion

Goal: move from alpha to full production/GA.

- [ ] Migrate encrypted vault blobs to object storage.
- [ ] Store vault revision metadata transactionally in PostgreSQL.
- [ ] Add transactional audit/outbox behavior.
- [ ] Remove production flat-file write paths after migration.
- [ ] Complete distributed rate limiting through Redis or API gateway.
- [ ] Prove distributed controls cannot be bypassed by restart or horizontal scaling.
- [ ] Configure encrypted database backups and point-in-time recovery.
- [ ] Configure versioned object-storage backups.
- [ ] Conduct and record destructive restore drill.
- [ ] Run production rollback drill.
- [ ] Protect the main branch and require all release gates in GitHub settings.

Evidence:

- migration logs;
- database/object-storage configuration records;
- restore-drill record;
- rollback-drill record;
- GitHub branch protection screenshot/export or settings API output.

## Phase 7, Signing And Release Certification

Goal: complete artifact trust and formal release process.

- [ ] Sign Windows artifacts.
- [ ] Sign macOS artifacts.
- [ ] Verify signatures and checksums before install.
- [ ] Confirm signed artifacts install successfully.
- [x] Pin CI actions by immutable commit SHA.
- [ ] Prove no release can bypass tests, scans, signing, or approval.
- [ ] Re-run the full test, build, scan, packaging, and install matrix.
- [ ] Conduct clean-room installation on each supported platform.
- [ ] Test upgrade from latest public version.
- [ ] Test rollback without vault or cloud data loss.

Evidence:

- signed artifacts;
- checksum/signature verification output;
- CI run URLs or logs;
- clean-room installation logs.

## Phase 8, Independent Review And Final GA Sign-Off

Goal: finish the post-alpha review checklist.

- [ ] Commission independent crypto/application security review.
- [ ] Penetration-test cloud API, admin, portal, local API, and sync.
- [ ] Resolve all critical and high findings.
- [ ] Triage medium/low findings with owners and deadlines.
- [ ] Fix release-blocking beta defects.
- [ ] Record zero open critical/high security findings.
- [ ] Obtain final engineering, security, operations, product, and legal sign-off.

Evidence:

- review report;
- pentest report;
- issue tracker export;
- final sign-off record.

## Execution Order

1. Finish Phases 1-5 to reach paid/evaluation alpha readiness.
2. Only then run alpha with constrained claims and collect defects.
3. Finish Phases 6-8 for 100% GA readiness.

## Current Best Next Slice

Start with Phase 1 and Phase 2 together:

- local web operation reconciliation;
- reveal/copy timeout;
- secret persistence checks;
- core Playwright coverage.

These unblock the clearest alpha risk: users clicking through the product and
finding broken states or accidental secret exposure.
