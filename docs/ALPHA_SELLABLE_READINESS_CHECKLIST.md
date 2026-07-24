# Pushkey Alpha Sellable Readiness Checklist

Status date: 2026-07-22

This checklist defines the bar for selling/evaluating Pushkey with alpha users.
It is intentionally narrower than the full production/GA checklist. Independent
security review, formal penetration testing, signing certificates, and
enterprise-scale infrastructure certification are tracked separately and are not
alpha blockers.

The full alpha-to-GA execution path lives in
[100_PERCENT_COMPLETION_TASKLIST.md](100_PERCENT_COMPLETION_TASKLIST.md).

## Current Assessment

Pushkey now meets the constrained alpha/sellable bar. The core local
product, CLI, MCP flow, admin auth, license/admin backend, web app,
admin/portal coverage, packaging smoke checks, and roadmap measurement are
materially advanced.

Alpha-to-market progress: 31/31 alpha blockers complete (100.0%).

PostgreSQL/object-storage sync migration, artifact signing, independent
review, penetration testing, and distributed production controls remain
post-Alpha / Public Beta work.

The dated launch boundary note lives in
[alpha-launch-boundary-note.md](alpha-launch-boundary-note.md).

## Alpha Launch Scope

Allowed alpha claims:

- Local encrypted vault V3.
- Desktop GUI and CLI for local secret management.
- Local web app through authenticated localhost API.
- MCP integration using scoped agent tokens.
- Admin/license portal with individual admin accounts, roles, sessions, CSRF,
  MFA, audit attribution, and abuse/rate-limit alerts.
- Cloud account/vault endpoints only as encrypted-blob alpha sync, not as a
  fully migrated PostgreSQL/object-storage production sync platform.

Do not claim for alpha:

- Independent security review completed.
- Penetration test completed.
- Distributed Redis/API-gateway rate limiting.
- PostgreSQL/object-storage cutover completed.
- Signed Windows/macOS artifacts unless signing has actually happened.
- Extension marketplace readiness unless store/package gates are complete.
- Full accessibility certification unless the audit passes.
- Production monitoring, backup, rollback, and drill evidence for full
  production/GA readiness.

## Alpha Blockers To Finish

### Product And UI

- [x] Reconcile every local web app operation with `docs/local-api-v1.md`.
- [x] Add loading, empty, error, locked, offline, and conflict states for core flows.
- [x] Add safe reveal/copy timeouts for secret values.
- [x] Verify secret values do not enter analytics, browser logs, persistent state,
  or screenshots.
- [x] Remove or disable unimplemented “coming soon” controls from alpha surfaces.
- [x] Validate all website/admin/product claims against tested capabilities.
- [x] Add basic keyboard navigation and focus checks for critical journeys.
- [x] Validate responsive layouts for supported alpha viewport sizes.

### Tests And E2E

- [x] Add Playwright coverage for local vault journeys:
  unlock, list, add, rotate, reveal timeout, inject, lock, and offline handling.
- [x] Add portal tests for license lookup, renewal request, support ticket creation,
  and privacy-safe failures.
- [x] Add admin journey tests for license, contact, audit, settings, support, and
  MFA/session boundaries.
- [x] Run the full Python suite.
- [x] Run both frontend lint/build pipelines.
- [x] Run package/install smoke tests from a clean environment.

### Packaging And Install

- [x] Make PyInstaller builds reproducible from a clean checkout.
- [x] Verify executable icons and version resources.
- [x] Produce the supported alpha OS/architecture artifacts.
- [x] Test upgrade without vault loss.
- [x] Ensure installer/download failures exit nonzero.
- [x] Handle unsupported OS/architecture explicitly.
- [x] Document arm64 as supported or unsupported for alpha.
- [x] Run fresh-machine smoke commands: `pushkey --help`, `pushkey init`,
  `pushkey app`.

### Operations

- [x] Configure actionable dashboards/alert targets for alpha operations.
- [x] Run an alpha-scale capacity test and record results.
- [x] Run a rollback drill in the alpha environment.
- [x] Confirm logs/metrics/alerts contain no plaintext secrets.
- [x] Record backup/restore procedure for the chosen alpha storage mode.

### Alpha Blocker

- [x] Confirm alerts reach the accountable operator.
  Delivery proof was captured in the accountable operator inbox via SMTP
  acceptance and IMAP receipt.

### Sync And Storage Scope

- [x] Cloud sync enabled for alpha only as opt-in encrypted-blob sync.
- [x] Document encrypted-blob-only limits and conflict behavior.
- [x] Keep PostgreSQL/object-storage migration out of alpha launch claims.

## Post-Alpha / Public Beta Blockers

These are important, but they are not required to begin paid/evaluation alpha
with the constrained claims above.

- [ ] Commission independent crypto/application security review.
- [ ] Penetration-test cloud API, admin, portal, local API, and sync.
- [ ] Resolve critical/high external-review findings.
- [ ] Triage medium/low external-review findings with owners and deadlines.
- [x] Add distributed Redis/API-gateway rate limiting.
- [x] Complete the PostgreSQL/object-storage migration code and remove
  flat-file production write paths. Reconciled 2026-07-24 against Phase 4 of
  `docs/PRODUCTION_READINESS_PLAN.md`, which is fully checked with coverage in
  `tests/test_cloud_vault_sync.py` and `tests/test_cloud_migrations.py`. This
  covers the code path only.
- [ ] Provision and cut over the hosted PostgreSQL and object storage. This is
  the external half of the item above and needs hosted credentials, so it stays
  open. Alpha claims remain constrained to opt-in encrypted-blob sync per
  `docs/release-readiness.md`.
- [ ] Sign Windows and macOS artifacts.
- [x] Configure branch protection and required release gates in GitHub settings.
- [ ] Complete production monitoring, backup, restore, and rollback drills.

## Alpha Go / No-Go

Alpha can start now because the Alpha Blocker above is checked. The post-Alpha
/ Public Beta blockers must be presented as future work, not as completed
production readiness.
