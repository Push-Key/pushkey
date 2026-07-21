# Pushkey 90 Percent Execution Checklist

Status date: 2026-07-21

Current measured readiness:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

Current result: 287/337 production items complete, 85.2%.
90% target: 304/337 production items complete.
Remaining needed for 90%: 17 additional verified items.

## Ground Rule

Do not mark a roadmap item complete unless one of these exists in the repo or
has been performed and recorded:

- production code and tests;
- CI workflow or packaging artifact validation;
- operator/security/legal documentation with a concrete procedure;
- a captured verification command;
- an external artifact or service configuration record.

## Track A, Local Backend And Operations Work

These are the next best local items because they can be implemented and tested
without pretending production infrastructure exists.

- [x] Add SMTP retry, timeout, and dead-letter behavior.
- [x] Add abuse detection and operational alerts.
- [x] Add security regression tests across multiple workers/instances.
- [x] Run concurrent license, contact, and vault writes.
- [ ] Verify zero-knowledge properties at API, logs, DB, and object storage.
- [ ] Load-test expected beta and launch concurrency.
- [x] Add transactional audit/outbox behavior.
- [x] Store vault revision metadata transactionally in the migration schema.
- [x] Add dashboard and alert configuration documents.
- [x] Add capacity-test and rollback-drill scripts or runbooks.

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_admin_api.py tests\test_cloud_vault_sync.py tests\test_cloud_migrations.py -q
.\.venv\Scripts\python.exe scripts\alpha_capacity_smoke.py --users 8 --iterations 4 --max-p95-ms 750
.\.venv\Scripts\python.exe scripts\alpha_rollback_drill.py
```

## Track B, Web Client And E2E Work

These can move many checklist items, but they require real browser automation and
careful UI verification.

- [ ] Reconcile all UI operations with the versioned local API.
- [ ] Complete loading, empty, error, locked, offline, and conflict states.
- [ ] Add safe secret reveal/copy timeouts.
- [ ] Prevent secret values from entering analytics, browser logs, or persistent state.
- [ ] Add keyboard navigation and focus management.
- [ ] Validate responsive layouts.
- [ ] Add Playwright coverage for core vault journeys.
- [x] Add portal tests for license lookup, renewal, support, and privacy-safe failures.
- [ ] Add admin Playwright coverage for license, contact, audit, settings, and support journeys.
- [x] Replace boilerplate `web/README.md` with an operator/developer runbook.

Verification:

```powershell
npm --prefix web-app run lint
npm --prefix web-app run build
npm --prefix web run lint
npm --prefix web run build
```

## Track C, Packaging And Installer Work

These are locally testable except code signing.

- [x] Make PyInstaller specs reproducible from a clean checkout.
- [ ] Verify icons and version resources.
- [ ] Produce supported OS/architecture artifacts.
- [x] Test upgrades without vault loss.
- [x] Align installer asset names with CI release artifacts.
- [ ] Verify checksums/signatures before installation.
- [ ] Fail with a nonzero exit code on unsuccessful installation.
- [ ] Handle unsupported OS/architecture explicitly.
- [ ] Add arm64 support or document it as unsupported.
- [ ] Prevent Windows shim self-resolution loops.
- [x] Test `npm install -g`, `npx`, upgrade, and uninstall in clean environments.
- [ ] Fresh-machine smoke tests run `pushkey --help`, `pushkey init`, and `pushkey app`.
- [ ] Release assets exactly match the npm download map.

External blocker:

- [ ] Sign Windows and macOS artifacts requires signing credentials.

## Track D, Post-Alpha / GA Gates

These should stay unchecked until real infrastructure or external records exist.
They are not blockers for a constrained alpha with accurate claims.

- [ ] Migrate encrypted vault blobs to object storage.
- [ ] Remove production flat-file write paths after migration.
- [ ] Add distributed rate limiting through Redis or the API gateway.
- [ ] Prove distributed controls cannot be bypassed by restart or horizontal scaling.
- [ ] Protect the main branch and require all release gates.
- [ ] Configure encrypted database backups and point-in-time recovery.
- [ ] Configure versioned object-storage backups.
- [ ] Conduct and record a destructive restore drill.
- [ ] Run a production rollback drill.
- [ ] Commission independent crypto/application security review.
- [ ] Penetration-test cloud API, admin, portal, local API, and sync.
- [ ] Resolve all critical and high findings.
- [ ] Obtain production monitoring evidence.
- [ ] Confirm signed artifacts install successfully.

## Execution Order

1. Finish Track A local backend/operations work.
2. Finish Track C local packaging/installer checks that do not require signing.
3. Finish Track B web/E2E coverage.
4. Stop before Track D unless the needed external services, credentials, or
   review artifacts are available.

## Stop Condition

If local work cannot reach 306/340 without Track D, record the exact measured
percentage and remaining blockers instead of marking unsupported items complete.
