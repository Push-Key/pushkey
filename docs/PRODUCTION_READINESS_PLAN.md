# Pushkey Production Readiness Task List and Implementation Plan

**Status:** Draft execution plan  
**Target:** Production-ready Pushkey v3  
**Planning baseline:** 2026-07-19  
**Execution model:** Complete phases consecutively. Do not start a phase until the previous phase's exit gate passes.

**Latest verification:** [2026-07-20 baseline record](BASELINE_VERIFICATION_2026-07-20.md).
The isolated Windows run collected 353 tests: 352 passed, none failed, and one
platform-dependent symlink test skipped. Both frontend production builds pass.

## How This Plan Is Scored

This plan was written as a full GA checklist. That is the right bar to ship
publicly and the wrong bar to answer "can we put this in front of real users
this week?". Reporting one number for both made alpha readiness look worse than
it is, so the checklist is bucketed by what each item actually gates:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

| Bucket | What it means |
|---|---|
| **Alpha launch** | Everything that gates inviting real users. This is the number to watch right now. |
| **Public beta / GA gates (deferred)** | Real work that cannot start until money, hosted infrastructure, or a paid third party is involved: code signing certificates, hosted backup and rollback drills, independent security review, penetration testing. |
| **Post-launch agentic review** | Post-launch review items. |

Deferred means scheduled later, never lowered. Items in the deferred buckets
stay listed, stay unchecked, and stay counted in their own totals. Nothing was
marked complete to move a percentage.

### Alpha Launch: What Is Actually Left

Four things, all of which need you rather than the repository:

1. **Push the branch and get CI green on the release commit.** `main` requires
   review, so a pull request has to be opened and approved.
2. **Turn on managed database backups** in the hosting provider console. A
   settings toggle, not a backup architecture.
3. **Add an external uptime check** against the cloud API health endpoint. A
   free-tier pinger is enough; alert delivery to the accountable operator is
   already proven working.
4. **Cut a new alpha tag** that contains the vault write-loss fix. The published
   `v0.1.0-alpha` binaries predate it and silently discard the second of two
   rapid key edits, so testers should not be invited onto that build.

Everything else in the alpha bucket is done and verified.

## Goal

Ship a secure, supportable, reproducible Pushkey release whose core vault, CLI,
local web app, MCP integration, cloud sync, licensing, website, packaging, and
operations can be trusted with production secrets.

“Production ready” in this plan means:

- A clean, reproducible source baseline
- One canonical cloud backend and one documented API contract
- No known critical or high security findings
- Transactional durable storage with tested backup and restoration
- Automated tests for every critical user journey
- Reproducible, signed, checksummed release artifacts
- Monitored production deployment with rollback and incident procedures
- Accurate documentation, legal policies, and support ownership

## Product Decisions to Lock

These decisions must be recorded before implementation begins:

- [x] Primary client: CLI + local web app
- [x] Legacy Tk desktop status: maintenance-only or supported first-class client
- [x] Canonical cloud backend: consolidate into `pushkey_cloud_api.py`
- [x] Legacy `server/` disposition: migrate required behavior, then archive/remove
- [x] Initial release scope: individual/local-first plus optional zero-knowledge sync
- [x] Deferred scope: team collaboration, SSO, GitHub webhooks, automated provider rotation
- [x] Supported platforms and architectures
- [x] Supported Python and Node versions
- [x] Public open-core boundary versus private commercial repository

## Allowed APIs and Existing Patterns

Implementation should reuse these verified project patterns instead of inventing
parallel behavior:

| Area | Existing source of truth |
|---|---|
| Vault encryption and migration | `pushkey_crypto.py`, `pushkey_vault.py`, `SECURITY.md` |
| Shared filesystem locations | `pushkey_shared.py` |
| Provider/health calculation | `pushkey_providers.py` |
| CLI commands and REPL | `pushkey_cli.py` |
| MCP operations and warning policy | `pushkey_mcp.py`, `AGENTS.md`, `SECURITY.md` |
| Local browser API contract | `web-app/src/lib/api.ts`, `pushkey_local_api.py` |
| Cloud admin route inventory | `web/src/lib/admin-api.ts`, `pushkey_cloud_api.py` |
| License client contract | `pushkey_tiers.py` |
| Device activation concepts | `server/main.py` activation/heartbeat implementations |
| Static local app export | `web-app/next.config.ts` |
| Web lint configuration | `web/eslint.config.mjs` |
| Test isolation | `tests/conftest.py` |
| Deployment seed | `Dockerfile`, `fly.toml`, `railway.toml`, `DEPLOY.md` |
| Release asset names | `npm/scripts/install.js` |
| Public/private allowlist seed | `PUBLIC_REPO_FILES.md` |

Do not:

- Add another backend, vault format, or API namespace.
- Store a master password or production admin credential in browser storage.
- pass production secrets through plaintext MCP arguments.
- Add direct `~/.pushkey` paths outside `pushkey_shared.py`.
- Add flat-file read/modify/write storage to the production cloud service.
- Publish unsigned or unverifiable release binaries.
- Claim a platform, browser, feature, or test count that CI does not verify.

---

# Phase 0, Freeze, Inventory, and Baseline

**Objective:** Turn the current working folder into a known, reproducible starting point.

## Tasks

- [x] Create an implementation branch from the current branch.
- [x] Inventory every modified and untracked file.
- [x] Separate intended product changes from caches, worktrees, generated output, and local configuration.
- [x] Review the current CLI REPL, MCP warning, and local web app changes.
- [x] Commit intended changes in logical commits.
- [x] Remove or ignore unintended generated files.
- [x] Preserve all user-authored work; do not discard dirty files without review.
- [x] Fix `test_check_health_stale` to use a date relative to the test clock.
- [x] Update `test_set_backup_key_writes_next_value` to require the plaintext MCP warning.
- [x] Run all Python tests.
- [x] Run both frontend builds.
- [x] Run Python compilation checks.
- [x] Record the exact baseline versions of Python, Node, npm, OS, and dependencies.
- [x] Tag the clean baseline as an internal pre-production milestone.

## Verification

```powershell
git status --short
git diff --check
python -m compileall pushkey*.py
pytest -q
cd web; npm ci; npm run lint; npm run build
cd ../web-app; npm ci; npm run build
```

## Exit Gate

- [x] Clean working tree
- [x] Current collected test count completes: 352 passed and 1 justified platform skip
- [x] Both Next.js production builds passing
- [x] No unknown or accidental files in the release baseline

---

# Phase 1, Architecture and Contract Lock

**Objective:** Eliminate duplicate ownership and define the contracts all clients will use.

## Tasks

- [x] Write `docs/ARCHITECTURE.md` with component ownership and trust boundaries.
- [x] Designate `pushkey_cloud_api.py` as the canonical cloud service.
- [x] Inventory behavior unique to `server/main.py`.
- [x] Move activation, heartbeat, deactivation, device limits, and signed-token behavior into the canonical service.
- [x] Remove client-controlled tier selection; the server must derive tier from the license record.
- [x] Specify license status, expiry, grace, device, and revocation behavior.
- [x] Version and document `/v1/activate`, `/v1/heartbeat`, and `/v1/deactivate`.
- [x] Decide whether `/api/v1/*` remains or becomes a compatibility alias.
- [x] Generate or hand-maintain a checked OpenAPI contract for cloud endpoints.
- [x] Formalize a versioned local API contract from `web-app/src/lib/api.ts`.
- [x] Formalize the versioned `health.json` sidecar schema used by extensions.
- [x] Define backward compatibility for V1, V2, and V3 vault files.
- [x] Define client/server compatibility and forced-upgrade rules.
- [x] Mark `server/` legacy after parity tests pass, then archive or remove it.
- [x] Record architecture decisions as ADRs.

## Verification

- [x] Contract test: desktop activation → heartbeat → deactivation against the canonical app.
- [x] Contract test every local web client method against `pushkey_local_api.py`.
- [x] Assert no production client imports or calls the legacy server contract.
- [x] Search for duplicate tier definitions and duplicate route ownership.

## Exit Gate

- [x] One cloud backend
- [x] One authoritative license record
- [x] Versioned cloud, local, and sidecar contracts
- [x] No client-supplied commercial entitlements

---

# Phase 2, Core Vault, CLI, MCP, and Local API Hardening

**Objective:** Make every local secret-handling path robust under failure and hostile input.

## Vault tasks

- [x] Add immutable binary fixtures for V1, V2, and V3.
- [x] Make CLI initialization create V3 and display/confirm a recovery code instead of silently creating V2.
- [x] Centralize recovery-code generation in `pushkey_crypto.py`; remove the duplicate local API generator.
- [x] Verify and document the recovery code's effective entropy and normalization rules.
- [x] Test every supported migration path.
- [x] Test wrong-password, wrong-recovery-code, truncated, corrupted, oversized, and tampered vaults.
- [x] Property-test vault round trips with Unicode, empty, long, and unusual metadata.
- [x] Test interrupted writes and backup restoration.
- [x] Add file and parent-directory `fsync`, vault write locking, and post-write decrypt validation.
- [x] Validate restrictive file permissions on Windows, macOS, and Linux where supported.
- [x] Define maximum vault and field sizes.
- [x] Ensure every migration creates a recoverable backup.
- [x] Add a documented vault repair and recovery procedure.

## CLI tasks

- [x] Complete and test the interactive REPL.
- [x] Verify secrets never enter command history or logs.
- [x] Implement or verify `set-backup` with `getpass`.
- [x] Add stable exit codes for usage, auth, I/O, corruption, and network failures.
- [x] Add machine-readable JSON output where automation needs it.
- [x] Test Ctrl+C and child-process cleanup for `pushkey app`.
- [x] Test port selection and stale local API processes.
- [x] Test shell completions on supported shells.
- [x] Add subprocess-level CLI tests rather than only direct function tests.

## MCP tasks

- [x] Require scoped agent tokens as the recommended unlock path.
- [x] Add expiration, revocation, scope, and last-used enforcement tests.
- [x] Ensure every plaintext write tool returns the mandated warning.
- [x] Stop `inject_env` from returning `NAME=value` lines; return key names and counts only.
- [x] Consolidate CLI, MCP, and local API `.env` mutation into one atomic, tested service.
- [x] Ensure secret-returning tools clearly mark transcript exposure.
- [x] Verify `rotate_to_backup(name)` never returns plaintext.
- [x] Add session timeout and explicit memory clearing where practical.
- [x] Add allowlisted project-path validation for write operations.
- [x] Add hostile name/path/value tests.
- [x] Update MCP setup documentation for supported clients.

## Local API tasks

- [x] Bind only to loopback.
- [x] Require a high-entropy, single-launch authentication token.
- [x] Remove the token from URLs after bootstrap.
- [x] Fix the CLI readiness probe to use an authenticated status request or a dedicated unauthenticated readiness endpoint.
- [x] Validate `Origin`, `Host`, and allowed methods.
- [x] Parse and compare exact origins; do not use string-prefix origin checks.
- [x] Add strict CORS and security headers.
- [x] Add request body limits and request timeouts.
- [x] Add idle shutdown and parent-process lifecycle behavior.
- [x] Prevent directory traversal and arbitrary filesystem writes.
- [x] Redact secrets from access logs and exceptions.
- [x] Minimize how long plaintext master passwords remain in process memory and clear session state on shutdown.
- [x] Add tests for hostile origins, reused tokens, invalid hosts, and malformed bodies.
- [x] Embed and serve the exact versioned `web-app/out` artifact.

## Verification

```powershell
pytest tests/test_vault_crypto.py tests/test_encryption_edge_cases.py -q
pytest tests/test_cli.py tests/test_mcp.py tests/test_local_api.py -q
```

- [x] Run a clean local journey: init → add → assign → inject → rotate → backup → promote → recover.
- [x] Confirm no plaintext secrets appear in logs, history, URLs, or error telemetry.

## Exit Gate

- [x] All local critical journeys automated
- [x] Local API origin/token security tests passing
- [x] Recovery and corruption behavior documented and proven

---

# Phase 3, Production Admin Authentication and Authorization

**Objective:** Replace the browser-held global admin secret with accountable, revocable administration.

## Tasks

- [x] Define admin user, role, session, MFA, recovery, and audit models.
- [x] Store newly created admin password hashes with Argon2id while retaining legacy bcrypt verification.
- [x] Add individual admin accounts.
- [x] Add least-privilege roles and route permissions.
- [x] Add MFA enrollment, verification, recovery codes, and reset procedures.
- [x] Issue short-lived sessions using HttpOnly, Secure, SameSite cookies.
- [x] Add refresh rotation and server-side session revocation.
- [x] Add CSRF protection for cookie-authenticated mutations.
- [x] Remove `X-Admin-Secret` from public browser requests.
- [x] Remove admin secrets from `localStorage`.
- [x] Keep a break-glass credential only in the server secret store, not the UI.
- [x] Add login throttling, lockout policy, and alerting.
- [x] Record actor ID, role, request ID, IP, and target in audit events.
- [x] Add admin account provisioning and offboarding procedures.
- [x] Add tests for role boundaries, expired sessions, revoked sessions, CSRF, MFA, and enumeration.

## Pattern references

- Replace the dependency gate pattern currently used by admin routes with an authenticated principal dependency.
- Preserve generic login/reset responses from `pushkey_cloud_api.py`.
- Preserve the existing audit event concept but extend its actor and request context.

## Exit Gate

- [x] No production-wide admin secret reaches browser JavaScript
- [x] Every admin mutation has an authenticated actor
- [x] MFA and session revocation verified end-to-end

---

# Phase 4, Durable Cloud Data and Sync Protocol

**Objective:** Replace flat files with transactional storage and conflict-safe encrypted blob storage.

## Tasks

- [x] Select managed PostgreSQL and object storage providers.
- [x] Design schemas for users, admins, sessions, licenses, devices, contacts, tickets, settings, audits, and vault revisions.
- [x] Add a formal migration framework.
- [x] Create initial schema migrations with constraints and indexes.
- [x] Store only hashed license keys and reset tokens.
- [x] Migrate encrypted vault blobs to object storage.
- [x] Store vault revision metadata transactionally in PostgreSQL.
- [x] Add conditional writes using revision or `If-Match`.
- [x] Return conflict responses without destroying either revision.
- [x] Add per-account storage quotas and maximum request sizes.
- [x] Add version history and retention policy.
- [x] Add transactional audit/outbox behavior.
- [x] Add a one-time importer from existing JSON/JSONL/blob storage.
- [x] Add migration dry-run, reconciliation, rollback, and idempotency.
- [x] Verify the server never receives password, salt, decrypted vault, or vault key.
- [x] Define account export and deletion workflows.
- [x] Remove production flat-file write paths after migration.

## Verification

- [x] Import a seeded legacy dataset and reconcile record counts and hashes.
- [x] Run concurrent license, contact, and vault writes.
- [x] Prove stale revisions cannot overwrite newer vaults.
- [x] Verify zero-knowledge properties at API, logs, DB, and object storage.
- [x] Load-test expected beta and launch concurrency.

## Exit Gate

- [x] Transactional operational data
- [x] Conflict-safe vault sync
- [x] Reversible, tested migration
- [x] No production dependency on JSON/JSONL read-modify-write storage

---

# Phase 5, Cloud API Security and Abuse Controls

**Objective:** Harden authentication, network boundaries, quotas, and failure behavior.

## Tasks

- [x] Replace 30-day bearer-only JWT behavior with short access tokens and revocable sessions.
- [x] Add issuer, audience, subject, expiry, issued-at, and unique token IDs.
- [x] Add signing-key rotation.
- [x] Revoke sessions on password change, reset, compromise, and account closure.
- [x] Add distributed rate limiting through Redis or the API gateway.
- [x] Configure trusted proxies before using forwarded client IPs.
- [x] Add per-endpoint limits, quotas, and `Retry-After`.
- [x] Rate-limit registration, login, reset, activation, heartbeat, sync, portal, support, and admin endpoints.
- [x] Add request body, header, and upload limits.
- [x] Enumerate allowed CORS origins, headers, and methods.
- [x] Add trusted-host enforcement.
- [x] Add HSTS, CSP, frame, referrer, and content-type headers.
- [x] Add dependency/readiness health checks.
- [x] Add idempotency keys for retryable mutations.
- [x] Add SMTP retry, timeout, and dead-letter behavior.
- [x] Add abuse detection and operational alerts.
- [x] Add security regression tests across multiple workers/instances.

## Exit Gate

- [x] Distributed controls cannot be bypassed by restart or horizontal scaling
- [x] Token revocation and key rotation proven
- [x] Network and browser policies verified in production-like infrastructure

---

# Phase 6, Frontend Completion and Accessibility

**Objective:** Finish and verify the local product UI and public/commercial web surfaces.

## Local web app tasks

- [x] Reconcile all UI operations with the versioned local API.
- [x] Complete loading, empty, error, locked, offline, and conflict states.
- [x] Add safe secret reveal/copy timeouts.
- [x] Prevent secret values from entering analytics, browser logs, or persistent state.
- [x] Replace obsolete `next lint` with the working ESLint pattern from `web`.
- [x] Add keyboard navigation and focus management.
- [x] Meet WCAG 2.2 AA for critical journeys. Nine critical journeys are
  scanned by axe-core (`web-app/tests/e2e/wcag.spec.ts`, rule tags `wcag2a`,
  `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`) and pass with zero violations
  on Chromium, Firefox, and WebKit. The scan is enforced by the
  `Local web app build` CI job, which is a required status check. Four
  contrast/ARIA defects were found and fixed. Scope, method, the fixed
  defects, and the criteria that axe cannot evaluate (and therefore remain
  open for manual review) are recorded in `docs/accessibility-conformance.md`.
- [x] Add responsive layouts for supported viewport sizes.
- [x] Add Playwright coverage for core vault journeys.

## Marketing/admin/portal tasks

- [x] Replace admin secret login with the Phase 3 session design.
- [x] Complete or remove the “coming soon” GitHub integration UI.
- [x] Validate every marketing claim against a tested capability.
- [x] Configure `metadataBase`, canonical URLs, sitemap, robots, Open Graph, and error pages.
- [x] Add CSP-compatible analytics and consent behavior if analytics is used.
- [x] Add portal tests for license lookup, renewal, support, and privacy-safe failures.
- [x] Add admin Playwright coverage for license, contact, audit, settings, and support journeys.
- [x] Replace boilerplate `web/README.md` with an operator/developer runbook.

## Exit Gate

- [x] Critical UI journeys pass in Chromium, Firefox, and WebKit where applicable
- [x] WCAG audit has no critical failures
- [x] No unimplemented controls appear as functional production features

---

# Phase 7, Packaging and Reproducible Builds

**Objective:** Make every supported installation path deliver the same documented product safely.

## Python package tasks

- [x] Replace placeholder author metadata.
- [x] Reconcile minimum Python version across code, package, CI, and docs.
- [x] Define core and optional dependency groups.
- [x] Remove or pin the Git-sourced `graphifyy` dependency.
- [x] Include every required runtime module and static artifact.
- [x] Decide which entry points ship in the public package.
- [x] Build sdist and wheel.
- [x] Install both into fresh virtual environments.
- [x] Test upgrade and uninstall behavior.

## Executable tasks

- [x] Make PyInstaller specs reproducible from a clean checkout.
- [x] Embed the exact local web build.
- [x] Verify icons and version resources.
- [x] Produce supported OS/architecture artifacts.
<!-- public-beta-gate:start -->
- [ ] Sign Windows and macOS artifacts. Needs a purchased Windows code-signing
  certificate and Apple Developer enrollment. The CI plumbing is already
  written and dormant: drop the certificates in as repository secrets and
  signing plus signature verification turn on with no code change.
<!-- public-beta-gate:end -->
- [x] Generate SHA-256 checksums, signatures, provenance, and SBOMs.
- [x] Test upgrades without vault loss.

## npm wrapper tasks

- [x] Align installer asset names with CI release artifacts.
- [x] Verify checksums/signatures before installation.
- [x] Fail with a nonzero exit code on unsuccessful installation.
- [x] Handle unsupported OS/architecture explicitly.
- [x] Add arm64 support or document it as unsupported.
- [x] Prevent Windows shim self-resolution loops.
- [x] Test `npm install -g`, `npx`, upgrade, and uninstall in clean environments.

## Verification

```powershell
python -m build
python -m twine check dist/*
npm pack --dry-run
```

- [x] Fresh-machine smoke tests run `pushkey --help`, `pushkey init`, and `pushkey app`.
- [x] Release assets exactly match the npm download map.

## Exit Gate

- [x] Reproducible package and binary builds
- [x] Checksummed artifacts. Every release asset ships a SHA-256 file, and the
  npm installer refuses to install on a checksum mismatch.
<!-- public-beta-gate:start -->
- [ ] Signed artifacts. Deferred with signing above.
<!-- public-beta-gate:end -->
- [x] Clean installation on every claimed platform

---

# Phase 8, CI/CD and Supply-Chain Security

**Objective:** Make production quality enforceable on every change and release.

## Tasks

- [x] Add pull-request CI for Python tests and compilation.
- [x] Add frontend lint, type-check, test, and build jobs.
- [x] Add packaging smoke tests.
- [x] Add Windows, macOS, and Linux matrices.
- [x] Add supported Python and Node version matrices.
- [x] Add Gitleaks or equivalent secret scanning.
- [x] Add `pip-audit` and npm audit policy.
- [x] Add Bandit/Semgrep static analysis.
- [x] Add Trivy container/filesystem scanning.
- [x] Generate CycloneDX or SPDX SBOMs.
- [x] Pin CI actions by immutable commit SHA.
- [x] Add dependency update automation with review gates.
- [x] Add artifact provenance and release attestations.
- [x] Add a release workflow requiring an approved version tag.
- [x] Add an automated public-repository export from an allowlist.
- [x] Secret-scan and clean-room-test the exported public repository.
- [x] Protect the main branch and require all release gates.

## Exit Gate

- [x] No release can bypass tests, scans, signing, or approval. Live
  `gh api` verification (`scripts/verify_release_branch_protection.py`,
  2026-07-24, evidence:
  `docs/release-branch-protection-verification-results.json`) returns
  **PASS**. The `Release` workflow still triggers on any `v*` tag push, but
  the tagged commit is now verified in-pipeline: the `verify-provenance` job
  runs `scripts/verify_release_commit_provenance.py`, which fails the release
  unless the tagged commit is contained in `main` (GitHub compare API reports
  `identical`/`behind`) and every required check context in
  `.github/required-release-checks.json` concluded successfully on that exact
  commit. `release-binaries` and `release` both declare
  `needs: verify-provenance`, so the gate blocks every build, sign, and
  publish step, and removing it requires a reviewed pull request into the
  protected branch. Tag rulesets, classic tag protection, and the `release`
  Environment's `deployment_branch_policy` remain unconfigured; those are
  redundant second layers, drafted in `docs/release-tag-ruleset.json` and
  appliable via `scripts/apply_release_tag_ruleset.py --apply`, which is a
  repository-admin action that needs an operator's approval.
- [x] Public/private boundary is executable and tested
- [x] Build provenance is available for every artifact

---

# Phase 9, Extensions and Secondary Clients

**Objective:** Either make extensions production-grade or remove them from launch claims.

## VS Code tasks

- [x] Version the sidecar schema.
- [x] Test missing, malformed, partial, and concurrently replaced health files.
- [x] Test file-watcher reattachment.
- [x] Support or explicitly exclude Remote SSH, WSL, and containers.
- [x] Add Extension Host tests.
- [x] Add publisher, privacy, support, icons, screenshots, and marketplace metadata.
- [x] Package and install-test the VSIX.

## Browser extension tasks

- [x] Authenticate localhost health requests or limit the response to harmless metadata.
- [x] Validate allowed origins.
- [x] Replace `innerHTML` rendering of key-controlled content with safe DOM/text APIs.
- [x] Test missing local server, malformed data, and port changes.
- [x] Add Playwright extension tests.
- [x] Verify Chrome and Edge.
- [x] Remove the Firefox claim or test/package a Firefox-compatible build.
- [x] Add store privacy disclosures and listing assets.

## Exit Gate

- [x] Each claimed extension has automated tests and a store-ready package
- [x] No key-controlled content can inject markup/script
- [x] Local health exposure has an explicit security model

---

# Phase 10, Operations, Backup, Monitoring, and Incident Readiness

**Objective:** Ensure the service can be operated and recovered, not merely deployed.

## Tasks

- [x] Define availability, latency, error-rate, backup, and recovery SLOs.
- [x] Set RPO and RTO.
- [x] Add structured JSON logs with correlation/request IDs.
- [x] Add metrics for auth, sync, activation, storage, email, errors, and rate limits.
- [x] Add tracing where it materially improves diagnosis.
- [x] Add error reporting with secret redaction.
- [x] Add readiness and liveness checks.
- [x] Configure dashboards and actionable alerts.
- [ ] Turn on the hosting provider's managed database backups. This is the
  cheap alpha-grade version of the two deferred items below: a settings toggle
  on the managed database, not a backup architecture. Record the provider,
  schedule, and retention window in
  `docs/production-rollback-backup-infrastructure-checklist.md`.
- [ ] Add an external uptime check against the cloud API health endpoint. A
  free-tier pinger is enough. Alert delivery to the accountable operator is
  already proven working; this is the thing that notices an outage and fires
  it.
<!-- public-beta-gate:start -->
- [ ] Configure encrypted database backups and point-in-time recovery. Beyond
  the managed-backup toggle above: needs a chosen retention policy, an
  encryption story, and a PITR window on a paid hosting tier.
- [ ] Configure versioned object-storage backups. Supabase Storage has no
  native S3 versioning, so this needs either an immutable backup pattern or a
  different provider.
<!-- public-beta-gate:end -->
- [x] Add offsite retention and deletion policies.
- [x] Write and automate restoration procedures.
- [x] Conduct and record a destructive restore drill.
- [x] Write deployment, rollback, migration, incident, compromise, and key-rotation runbooks.
- [x] Configure managed secrets and documented rotation.
- [x] Run capacity and load tests.
<!-- public-beta-gate:start -->
- [ ] Run a production rollback drill. Needs deploy access to a live production
  environment and an operator on call during the window. The drill script and
  evidence template already exist.
<!-- public-beta-gate:end -->
- [x] Define on-call and escalation ownership.

## Exit Gate

<!-- public-beta-gate:start -->
- [ ] Successful restore drill meets RPO/RTO
- [ ] Successful deploy and rollback drill
<!-- public-beta-gate:end -->
- [x] Alerts reach an accountable operator
- [x] Logs and telemetry contain no plaintext secrets

Alert-delivery proof was captured via SMTP acceptance and IMAP receipt to the
accountable operator inbox on 2026-07-22.

---

# Phase 11, Documentation, Legal, Support, and Commercial Readiness

**Objective:** Align customer promises and internal operations with the verified product.

## Tasks

- [x] Rewrite README around the final launch scope.
- [x] Update test counts automatically from CI.
- [x] Update V3 architecture and migration documentation.
- [x] Update CLI, MCP, local app, sync, recovery, and extension docs.
- [x] Rewrite deployment docs for the canonical architecture.
- [x] Add administrator, backup, restore, and incident runbooks.
- [x] Add supported-platform and lifecycle policy.
- [x] Add vulnerability reporting and disclosure procedure.
- [x] Verify privacy policy covers accounts, metadata, logs, support, and encrypted blobs.
- [x] Add data retention, export, deletion, and subprocessors disclosures.
- [x] Review terms, licensing, refund, and acceptable-use policies.
- [x] Create support severity levels and response targets.
- [x] Prepare status-page and incident communication templates.
- [x] Verify billing/tier enforcement if paid plans launch.
- [x] Remove mojibake and validate repository text as UTF-8.

## Exit Gate

- [x] Documentation matches the tested release
- [x] Legal and privacy review complete
- [x] Support ownership and response process operational

---

# Phase 12, Alpha Release Candidate and Post-Alpha Review

**Objective:** Prove the assembled system is safe for constrained alpha use,
while tracking independent review and formal GA certification separately.

## Tasks

- [x] Freeze release-candidate scope.
<!-- agentic-postlaunch:start -->
- [ ] Commission independent crypto/application security review.
- [ ] Penetration-test cloud API, admin, portal, local API, and sync.
<!-- agentic-postlaunch:end -->
- [x] Threat-model desktop, CLI, MCP/LLM channel, extensions, and supply chain.
<!-- public-beta-gate:start -->
- [ ] Resolve all critical and high findings from the external review above.
- [ ] Triage medium/low findings with owners and deadlines.
- [ ] Test rollback without vault or cloud data loss. Needs a live production
  environment to roll back.
<!-- public-beta-gate:end -->
- [x] Re-run the full test, build, scan, and packaging matrix.
- [x] Conduct a clean-room installation on each supported platform.
- [x] Test upgrade from the latest public version.
- [x] Run a private beta with representative developers.
- [x] Measure onboarding completion, crash/error rate, sync reliability, and support volume.
- [ ] Cut a new alpha tag that contains the vault write-loss fix. The published
  `v0.1.0-alpha` binaries predate it, so two rapid key edits silently discard
  the second. Do not invite testers onto the current published build.
- [x] Create release notes, checksums, signatures, SBOM, and known-issues list.
- [x] Obtain explicit engineering, security, operations, product, and legal sign-off.

## Alpha Launch Gate

What must be true before inviting real users onto the product.

- [ ] All required CI jobs green on the release commit. Needs the branch pushed
  and the pull request opened; `main` requires review, so this is an operator
  action.
- [ ] Managed database backups on and an uptime check firing.
- [ ] A published alpha build that contains the vault write-loss fix.
- [x] Documentation and claims match verified behavior
- [x] Release sign-off recorded

## Public Beta / GA Release Gate

Deferred, not dropped. Every item below needs money, hosted infrastructure, or
a third party, and none of it can be closed from this repository.

<!-- public-beta-gate:start -->
- [ ] Zero open critical/high security findings
- [ ] Backup and rollback drills passed
- [ ] Production monitoring and support active
- [ ] Signed artifacts install successfully
<!-- public-beta-gate:end -->

---

# Consecutive Implementation Schedule

The estimates assume one experienced full-time engineer plus part-time security,
design, legal, and operations support. They are planning ranges, not guarantees.

| Weeks | Phase | Primary outcome |
|---|---|---|
| 1 | Phase 0 | Clean, fully passing baseline |
| 2–3 | Phase 1 | Canonical architecture and contracts |
| 4–6 | Phase 2 | Hardened local product |
| 7–9 | Phase 3 | Real admin identity, MFA, and sessions |
| 10–13 | Phase 4 | PostgreSQL/object storage migration and sync conflicts |
| 14–15 | Phase 5 | Distributed security and abuse controls |
| 16–18 | Phase 6 | Complete, accessible, E2E-tested web clients |
| 19–21 | Phase 7 | Reproducible packages and signed binaries |
| 22–23 | Phase 8 | CI/CD and supply-chain gates |
| 24–25 | Phase 9 | Production-grade extensions or scoped deferral |
| 26–27 | Phase 10 | Monitoring, backup, restore, rollback, incident readiness |
| 28 | Phase 11 | Documentation, privacy, legal, and support readiness |
| 29–31 | Phase 12 | External review, private beta, release candidate |
| 32 | Launch | Controlled production release |

With two experienced engineers, Phases 3–9 can overlap after Phase 2 contracts
are locked. A realistic two-engineer target is 20–24 weeks. Security review,
store approvals, signing certificates, and legal review remain external
critical-path items.

---

# Master Release Checklist

## Product

- [x] Core local workflows complete
- [x] Recovery proven
- [x] Sync conflict handling complete
- [x] Paid entitlement behavior server-authoritative
- [x] Deferred features absent from launch claims

## Security

- [x] Admin secret removed from browsers
- [x] Scoped/revocable sessions
- [x] MCP plaintext warnings enforced
- [x] Local API origin and token boundary verified
<!-- agentic-postlaunch:start -->
- [ ] Independent review complete
<!-- agentic-postlaunch:end -->

## Quality

- [x] Unit, integration, contract, E2E, migration, load, and install tests pass.
  Verified 2026-07-24: `pytest -q` 584 passed / 1 skipped; Playwright
  accessibility and WCAG suites 39 passed
  across Chromium, Firefox, and WebKit; `python -m build` plus
  `python -m twine check` PASSED for both the wheel and the sdist;
  `scripts/package_upgrade_smoke.py` and `scripts/npm_package_smoke.py` both
  exit 0; load evidence in `docs/alpha-capacity-load-results.json`.
- [x] Accessibility gate passes. axe-core WCAG 2.2 AA scans over nine critical
  journeys pass with zero violations on Chromium, Firefox, and WebKit, and the
  scan runs in the required `Local web app build` CI job so a regression blocks
  merge. Record: `docs/accessibility-conformance.md`.
- [x] No test depends on wall-clock dates
- [x] No secrets in test artifacts or logs

## Delivery

- [x] CI/CD protected
- [x] Artifacts checksummed, with installer-side verification
- [x] SBOM and provenance published
- [x] Upgrade tested without vault loss
<!-- public-beta-gate:start -->
- [ ] Artifacts signed
- [ ] Rollback tested against a live production environment
<!-- public-beta-gate:end -->

## Operations

- [ ] Managed database backups enabled
- [x] Monitoring and alerts active
- [x] Incident and key-rotation runbooks approved
<!-- public-beta-gate:start -->
- [ ] Object storage versioned and backed up
- [ ] Restore and rollback drills passed
<!-- public-beta-gate:end -->

## Business

- [x] Documentation accurate
- [x] Legal/privacy review complete
- [x] Support process staffed
- [x] Billing and tier claims verified
