# Pushkey Launch Execution Tasklist

Status date: 2026-07-24

Measured production-readiness progress:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

Current result: 320/327 alpha-launch items complete, 97.9%. The 18 deferred
public-beta / GA gates and 3 post-launch review items are counted separately;
see "How This Plan Is Scored" in `docs/PRODUCTION_READINESS_PLAN.md`.

## Completed in this execution pass

- [x] Add reproducible roadmap progress tooling.
- [x] Add focused tests for roadmap progress parsing and CLI output.
- [x] Add minimal GitHub Actions CI for Python tests/compilation.
- [x] Add GitHub Actions Dependabot coverage for workflows, `web`, and `web-app`.
- [x] Update stale Phase 1 roadmap checkboxes from verified architecture, ADR, OpenAPI, and contract-test evidence.
- [x] Consolidate CLI, MCP, local API, and GUI `.env` mutation through a shared service.
- [x] Add MCP allowlisted project-path validation and hostile input tests.
- [x] Add admin role permissions and actor/request audit attribution tests.
- [x] Add packaging smoke and security scan CI follow-up.
- [x] Add admin MFA enrollment, recovery codes, login enforcement, and reset tests.
- [x] Harden cloud API request limits, CORS, trusted hosts, security headers, and readiness checks.
- [x] Remove the Git-sourced package dependency and test package metadata/entry points.
- [x] Add release workflow checksums, SBOM/provenance attestations, and public-export secret scanning.
- [x] Replace browser extension key-list `innerHTML` rendering with safe DOM/text APIs.
- [x] Add data-governance coverage for privacy, retention, export, deletion, and subprocessors.
- [x] Add vault unusual-metadata and restrictive-permission regression tests.
- [x] Add browser extension health-payload sanitization tests.
- [x] Add cloud sync `If-Match`, conflict, history, idempotency, export, and deletion tests.
- [x] Add structured request logs, request IDs, and operational metrics.
- [x] Replace web-app `next lint` with ESLint 9 flat config and CI lint coverage.
- [x] Add release-candidate scope, threat-model, legal/commercial, and backup/restore runbooks.
- [x] Add migration framework, schema baseline, dry-run importer, and reconciliation tests.
- [x] Add user JWT signing-key rotation and `Retry-After` rate-limit headers.

## Active priority queue

Phase 2 execution details live in [PHASE2_EXECUTION_TASKLIST.md](PHASE2_EXECUTION_TASKLIST.md).
The 5-task dependency chain lives in [CONSECUTIVE_LAUNCH_TASKS.md](CONSECUTIVE_LAUNCH_TASKS.md).
The alpha-to-GA completion path lives in
[100_PERCENT_COMPLETION_TASKLIST.md](100_PERCENT_COMPLETION_TASKLIST.md).

### 1. Close Phase 1 contracts

- [x] Write the versioned local API contract from `web-app/src/lib/api.ts`.
- [x] Add contract tests for every local web client method against `pushkey_local_api.py`.
- [x] Define `health.json` sidecar schema v1 for VS Code/browser extensions.
- [x] Add schema tests for healthy, stale, missing, malformed, and partial sidecar data.
- [x] Define client/server compatibility and forced-upgrade rules.
- [x] Add a guard test proving production clients do not import or call `server/main.py`.
- [x] Archive, remove, or mechanically exclude `server/` after parity checks.

### 2. Fix Phase 2 security blockers

- [x] Add CLI `set-backup` using `getpass`.
- [x] Add stable CLI exit-code constants and tests.
- [x] Add MCP token expiration and enforcement.
- [x] Remove `old_value_hint` from `rotate_to_backup`.
- [x] Redact local API injection responses so they do not return `NAME=value`.
- [x] Fix `test_gitignore_failure_prevents_env_secret_write`.
- [x] Consolidate CLI, MCP, and local API `.env` mutation into one atomic service.
- [x] Add allowlisted project-path validation for write operations.

### 3. Continue Phase 3 admin auth

- [x] Define admin user, role, session, MFA, recovery, and audit models.
- [x] Add individual admin-account lifecycle endpoints.
- [x] Add least-privilege roles and route permissions.
- [x] Add MFA enrollment, recovery codes, and reset flow.
- [x] Add session refresh rotation and broad server-side revocation.
- [x] Add login throttling, lockout policy, and alert audit events.
- [x] Record actor ID, role, request ID, IP, and target in admin audit events.
- [x] Add tests for role boundaries, expired sessions, revoked sessions, disabled admins, CSRF, MFA, and enumeration.

### 4. Parallel low-risk lanes

- [x] Add `web-app` lint modernization so CI can run lint there.
- [x] Add package metadata cleanup and supported Python/Node version decision.
- [x] Add npm installer failure/unsupported-platform tests.
- [x] Update `DEPLOY.md` to emphasize one worker/one machine until Phase 4 storage migration.
- [x] Inventory extension launch claims and decide defer/remove/ship.
  - Decision: defer browser and VS Code extensions until their package/store gates pass.

## Sub-agent assignment rules

- Use `gpt-5.5` with low reasoning for docs, CI, checklist, package metadata, and simple tests.
- Use `gpt-5.6-luna` or `gpt-5.6-terra` for medium-risk code changes.
- Keep vault crypto, auth/session/MFA, cloud storage migration, and sync conflict design under main-agent coordination.
- Give each worker a disjoint file ownership set.
- Prefer patch-producing workers over broad read-only audits now that the roadmap is measured.
