# Pushkey Consecutive Launch Tasks

Status date: 2026-07-21

This is the 5-task dependency chain. Parallel workers can help inside each task,
but these five should be completed in order.

## 1. Lock The Baseline And Contracts

Goal: make the roadmap measurable and freeze the contracts the rest of launch
work depends on.

- [x] Add roadmap progress tooling.
- [x] Add minimal CI.
- [x] Add local API v1 contract.
- [x] Add health sidecar v1 contract.
- [x] Add production-entrypoint guard against legacy `server/main.py`.
- [x] Run full Python suite.
- [x] Run both frontend builds.
- [x] Define forced-upgrade/client compatibility rules.
- [x] Decide product locks: primary client, desktop status, launch scope, supported Python/Node/OS/arch, public/private repo boundary.
- [x] Archive, remove, or mechanically exclude legacy `server/`.

Exit gate:

- [x] One canonical cloud backend.
- [x] Versioned cloud, local API, and sidecar contracts.
- [x] Full baseline tests/builds pass.

## 2. Harden Local Secret Handling

Goal: make CLI, MCP, local API, and vault workflows safe enough for real
developer secrets.

- [x] Remove MCP `rotate_to_backup` plaintext hint.
- [x] Redact local API injection responses.
- [x] Add MCP agent-token expiration enforcement.
- [x] Add CLI `set-backup <NAME>` using `getpass`.
- [x] Add stable CLI exit codes.
- [x] Fix local API `.gitignore` failure atomicity.
- [x] Add allowlisted project-path validation for writes.
- [x] Consolidate CLI/MCP/local API `.env` mutation into one atomic service.
- [x] Add subprocess-level CLI tests.
- [x] Add recovery/repair procedure documentation.
- [x] Run clean journey: init, add, assign, inject, rotate, backup, promote, recover.

Exit gate:

- [x] Local critical journeys automated.
- [x] Local API/MCP plaintext exposure rules verified.
- [x] Recovery and corruption behavior documented and proven.

## 3. Finish Admin Auth And Cloud Authority

Goal: make all cloud/admin actions authenticated, accountable, and server
authoritative.

- [x] Argon2id admin password hashes.
- [x] HttpOnly/Secure/SameSite admin sessions.
- [x] CSRF protection.
- [x] Remove browser-held admin secret.
- [x] Add individual admin-account lifecycle.
- [x] Add roles and route permissions.
- [ ] Add MFA enrollment and recovery codes.
- [ ] Add refresh rotation and broad session revocation.
- [x] Add actor/request attribution to every admin mutation audit event.
- [x] Add tests for roles, disabled admins, expired sessions, revoked sessions, CSRF, MFA, and enumeration.

Exit gate:

- [x] No production-wide admin secret reaches browser JavaScript.
- [x] Every admin mutation has an authenticated actor.
- [x] MFA and session revocation verified end-to-end.

## 4. Replace Temporary Cloud Storage And Add Abuse Controls

Goal: remove flat-file production limits and make the cloud service safe on
public infrastructure.

- [ ] Choose PostgreSQL provider.
- [ ] Choose object-storage provider.
- [ ] Design schemas and migrations.
- [ ] Migrate encrypted vault blobs to object storage.
- [ ] Add revision/`If-Match` conflict-safe sync.
- [ ] Add importer from existing JSON/JSONL/blob storage.
- [ ] Remove production flat-file write paths.
- [ ] Add distributed rate limiting.
- [ ] Add trusted proxy/host/CORS/security-header policy.
- [ ] Add request limits, idempotency keys, SMTP retry, and abuse alerts.

Exit gate:

- [ ] Transactional operational data.
- [ ] Conflict-safe vault sync.
- [ ] Distributed controls survive restart/horizontal scaling.

## 5. Ship Release Candidate

Goal: package, verify, operate, review, and launch.

- [ ] Complete frontend states, accessibility, and Playwright coverage.
- [ ] Decide extension scope: ship, beta, or defer.
- [ ] Build and install-test sdist/wheel.
- [ ] Reproduce PyInstaller builds from clean checkout.
- [ ] Align npm wrapper asset names and checksum/signature verification.
- [ ] Add CI matrices, security scans, SBOM, and provenance.
- [ ] Configure monitoring, backups, restore drill, and rollback drill.
- [ ] Complete legal/privacy/support docs.
- [ ] Commission independent security review.
- [ ] Resolve critical/high findings.
- [ ] Run private beta.
- [ ] Produce signed artifacts, checksums, SBOM, release notes, and final sign-off.

Exit gate:

- [ ] Zero open critical/high security findings.
- [ ] Signed artifacts install on every claimed platform.
- [ ] Backup and rollback drills passed.
- [ ] Documentation and claims match verified behavior.
