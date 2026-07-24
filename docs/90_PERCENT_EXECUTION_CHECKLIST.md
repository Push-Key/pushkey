# Pushkey 90 Percent Execution Checklist

Status date: 2026-07-24

Current measured readiness:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

Current result: 317/337 production items complete, 94.1%.
90% target: already exceeded.
Remaining needed for 90%: 0 additional verified items.
The remaining open items are external Track D gates. The last local Track A
load-test slice is recorded in `docs/alpha-capacity-load-results.json`.

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
- [x] Verify zero-knowledge properties at API responses, logs, database
  migration metadata, export paths, and object-storage abstraction.
- [x] Load-test expected beta and launch concurrency.
- [x] Add transactional audit/outbox behavior.
- [x] Store vault revision metadata transactionally in the migration schema.
- [x] Add dashboard and alert configuration documents.
- [x] Add capacity-test and rollback-drill scripts or runbooks.

Track A is now fully complete; the remaining blockers are external Track D
gates.

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_admin_api.py tests\test_cloud_vault_sync.py tests\test_cloud_migrations.py -q
.\.venv\Scripts\python.exe scripts\alpha_capacity_smoke.py --users 8 --iterations 4 --max-p95-ms 750
.\.venv\Scripts\python.exe scripts\alpha_capacity_smoke.py --users 16 --iterations 8 --output docs\alpha-capacity-load-results.json --max-p95-ms 1000
.\.venv\Scripts\python.exe scripts\alpha_rollback_drill.py
```

## Track B, Web Client And E2E Work

These can move many checklist items, but they require real browser automation and
careful UI verification.

- [x] Reconcile all UI operations with the versioned local API.
- [x] Complete loading, empty, error, locked, offline, and conflict states.
- [x] Add safe secret reveal/copy timeouts.
- [x] Prevent secret values from entering analytics, browser logs, local storage,
  session storage, screenshots, or persistent app state.
- [x] Add keyboard navigation and focus management.
- [x] Validate responsive layouts.
- [x] Add Playwright coverage for core vault journeys.
- [x] Add portal tests for license lookup, renewal, support, and privacy-safe failures.
- [x] Add admin Playwright coverage for license, contact, audit, settings,
  support, MFA, disabled-admin, expired-session, revoked-session, and role
  boundary journeys.
- [x] Replace boilerplate `web/README.md` with an operator/developer runbook.

Verification:

```powershell
npm --prefix web-app run lint
npm --prefix web-app run build
npm --prefix web run lint
npm --prefix web run build
```

## Track C, Packaging And Installer Work

These are locally testable except code signing, which is deferred to Public
Beta.

- [x] Make PyInstaller specs reproducible from a clean checkout.
- [x] Verify icons and version resources.
- [x] Produce supported OS/architecture artifacts.
- [x] Test upgrades without vault loss.
- [x] Align installer asset names with CI release artifacts.
- [x] Verify checksums before installation.
- [x] Fail with a nonzero exit code on unsuccessful installation.
- [x] Handle unsupported OS/architecture explicitly.
- [x] Add arm64 support or document it as unsupported.
- [x] Prevent Windows shim self-resolution loops.
- [x] Test `npm install -g`, `npx`, upgrade, and uninstall in clean environments.
- [x] Fresh-machine smoke tests run `pushkey --help`, `pushkey init`, and `pushkey app`.
- [x] Release assets exactly match the npm download map.

External blocker:

- [ ] Sign Windows and macOS artifacts. Deferred to Public Beta; requires
  signing credentials.

## Track D, Post-Alpha / GA Gates

These should stay unchecked until real infrastructure or external records exist.
They are not blockers for a constrained alpha with accurate claims.

- [x] Migrate encrypted vault blobs to object storage.
- [x] Remove production flat-file write paths after migration.
- [x] Add distributed rate limiting through Redis or the API gateway.
- [x] Prove distributed controls cannot be bypassed by restart or horizontal scaling.
- [x] Protect the main branch and require all release gates.
- [ ] Configure encrypted database backups and point-in-time recovery.
- [ ] Configure versioned object-storage backups.
- [ ] Conduct and record a destructive restore drill.
- [ ] Run a production rollback drill.
- [ ] Commission independent crypto/application security review.
- [ ] Penetration-test cloud API, admin, portal, local API, and sync.
- [ ] Resolve all critical and high findings.
- [ ] Obtain production monitoring evidence.
- [ ] Verify artifact signatures before installation. Deferred to Public Beta.
- [ ] Confirm signed artifacts install successfully (Public Beta gate).

## Execution Order

1. Finish Track A local backend/operations work.
2. Finish Track C local packaging/installer checks that do not require signing.
3. Finish Track B web/E2E coverage.
4. Stop before Track D unless the needed external services, credentials, or
   review artifacts are available.

## Stop Condition

If local work stalls before the next verified slice without Track D, record the
exact measured percentage and remaining blockers instead of marking unsupported
items complete.

## 90 Percent Sprint Checklist

Use this as the working queue for the remaining local-only work.

- [x] Run the beta/launch concurrency smoke and record the JSON result in
  `docs/alpha-capacity-results.json`.
- [x] Capture a short readiness note that explains the alpha launch boundary,
  current limitations, and what is still deferred to GA.
- [x] Verify artifact signature handling is documented separately from checksum
  handling so unsigned alpha builds are not overstated.
- [x] Confirm alert routing reaches the accountable operator and record the
  delivery proof.
- [x] Re-run the roadmap tracker after each completed slice and log the new
  completion number in the checklist (317/337).

Evidence captured:

- `python scripts/alpha_capacity_smoke.py --users 8 --iterations 4 --max-p95-ms 750`
- `python scripts/alpha_capacity_smoke.py --users 16 --iterations 8 --output docs/alpha-capacity-load-results.json --max-p95-ms 1000`
- `python scripts/alpha_rollback_drill.py`
- `python scripts/roadmap_progress.py`
- `docs/alpha-capacity-load-results.json`
- `docs/alpha-launch-boundary-note.md`

### Immediate Execution Order

1. Use `docs/production-external-gate-handoff-checklist.md` for the remaining
   external evidence fields.
2. Re-run `scripts/roadmap_progress.py` and record whether the total moved.
3. If the tracker still sits below the next verified slice, stop and list the
   remaining blockers rather than widening scope.
