# Pushkey Release Readiness

Status: Phase 12 release-candidate control document.

## Release-Candidate Scope

The release candidate is limited to:

- local encrypted vault V3;
- desktop GUI and CLI;
- local web app served by the authenticated local API;
- MCP integration with scoped agent-token unlock;
- optional cloud sync as encrypted-blob storage only, with ETag conflict
  detection and no server-side plaintext access or merge logic;
- cloud license/device activation API;
- cloud admin API with individual admin accounts, roles, sessions, CSRF, MFA,
  audit attribution, and release-gated operations;
- browser and VS Code extensions only as beta clients unless their package/store
  gates pass.

Deferred features must not appear in launch claims:

- PostgreSQL/object-storage sync migration;
- distributed rate limiting;
- PostgreSQL/object-storage-backed multi-device sync with server-side merge or
  conflict resolution;
- signed marketplace artifacts;
- external security review results.

## Alpha Release

The invite-only Alpha may ship unsigned desktop and CLI builds. Signing is
deferred for Alpha, not completed, and becomes mandatory before Public Beta.

Alpha requirements:

- unsigned builds are permitted;
- distribution is invite-only;
- every tester must be explicitly told the build is unsigned before download or
  install;
- testers should use test credentials and noncritical secrets only;
- no real production secrets, customer data, or production credentials may be
  used for Alpha testing;
- every distributed artifact must include a SHA-256 checksum;
- every artifact must identify the version, release tag, and commit SHA;
- downloads must only be distributed through the official Pushkey domain, the
  official GitHub release, or another approved channel;
- automatic updates must remain disabled unless update integrity is
  independently protected;
- the release must be labeled `Pushkey Alpha` or `Developer Preview`;
- the Alpha must not be described as production-ready, enterprise-ready, or
  suitable for critical production credentials;
- Windows code signing, macOS signing and notarization, signed-artifact
  verification, and clean-machine installation testing are mandatory before
  Public Beta.

## Threat Model Summary

Primary assets:

- plaintext API keys;
- vault master password and recovery code;
- encrypted vault blobs;
- admin sessions and MFA recovery codes;
- license/device tokens;
- signing and release credentials.

Primary trust boundaries:

- local app to browser/webview;
- CLI/MCP to LLM/chat channel;
- local vault to cloud sync;
- admin browser to cloud API;
- private repository to public repository export;
- CI artifacts to release downloads.

Required controls before launch:

- no plaintext secrets in logs, analytics, responses, or MCP long-lived-key flows;
- authenticated local API sessions and strict local origins;
- admin sessions with CSRF, MFA, revocation, and role checks;
- reproducible package artifacts with checksums, SBOM, and provenance;
- incident, backup, restore, rollback, and key-rotation runbooks.

The concrete infrastructure checklist for production backup/rollback evidence
lives in
[production-rollback-backup-infrastructure-checklist.md](production-rollback-backup-infrastructure-checklist.md).
That checklist does not establish branch protection or release-gate
enforcement. Those settings are captured separately in the external-gate
handoff checklist and the repository settings API output.

The operator handoff for the remaining external production gates lives in
[production-external-gate-handoff-checklist.md](production-external-gate-handoff-checklist.md).
Use it as the companion record for backups, restore/rollback drills,
monitoring evidence, alert delivery, alpha packaging and checksum publication,
and the deferred Public Beta signing and signed-install verification gates.

## Release Governance Evidence

Current in-repo evidence:

- `docs/PRODUCTION_READINESS_PLAN.md` still leaves the backup, restore,
  rollback, signing, and review items unchecked.
- `docs/production-external-gate-handoff-checklist.md` captures the GitHub
  branch-protection and release-gate API evidence.
- `docs/100_PERCENT_COMPLETION_TASKLIST.md` and
  `docs/REMAINING_TO_100_PERCENT_TASKLIST.md` now reflect the configured
  branch-protection state.

- `docs/release-branch-protection-verification-results.json` records the
  2026-07-24 live `gh api` verdict, **PASS**: the `verify-provenance` job gates
  the entire release workflow, so a release cannot be cut from a commit that is
  not contained in `main` or that lacks successful required checks.
- `docs/accessibility-conformance.md` records WCAG 2.2 AA conformance for the
  local web app's critical journeys, enforced by a required CI check.

External evidence still required before any GA claim:

- signing credentials and signed-artifact install proof;
- hosted backup, restore, and rollback drill records;
- independent security review and penetration-test reports.

## Defects Fixed After The Alpha Tag

Fixes landed after `v0.1.0-alpha` was published. They are not in the published
alpha artifacts and must be included in the next release candidate.

| Severity | Component | Defect | User impact | Fix |
|---|---|---|---|---|
| High | Local vault (`pushkey_vault.py`) | Rolling and migration backup filenames were built from `datetime.now()` and created exclusively (`"xb"`). `datetime.now()` has ~16ms granularity on Windows, so two vault writes inside one clock tick produced the same filename and raised `FileExistsError`. | The second of any two rapid vault mutations failed. Through the local API this surfaced as a rolled-back HTTP 500, so the write was silently discarded. Reproduced deterministically; 200 rapid backups previously collided on the second one. | Same-tick names now disambiguate with a counter suffix, still exclusively created so no backup can be clobbered. Backup pruning breaks mtime ties by name so survivors are deterministic. Regression tests in `tests/test_vault_crypto.py`. |
| Medium | Local web app | Four WCAG 2.2 AA defects: `aria-label` on a roleless toast container, and three foreground/background pairs below the 4.5:1 contrast minimum. | Screen-reader users got no name for the notification region; low-vision users could not reliably read the sidebar footer, destructive buttons, or count badges. | See `docs/accessibility-conformance.md`. |
| Medium | Build/CI | `web-app/package-lock.json` was out of sync with `package.json`, and both frontends failed `npm audit --audit-level=high` on a transitive `sharp` advisory. | Every `npm ci` step in CI would have failed, and the security-scan job with it. | Lockfile regenerated; `sharp` overridden to `^0.35.3` in both frontends. |
| Low | Test harness | `pytest.ini` pinned `--basetemp` to a single repo-local `.pytest_tmp`. pytest deletes that whole tree at session start, so a second pytest run destroyed the live `tmp_path` directories of a run already in progress. | Phantom failures and teardown `PermissionError`s landed on whichever unrelated test was executing and never reproduced in isolation. Two such failures were observed and initially misread as product defects. | Each session now gets its own `.pytest_tmp/s<pid>` subdirectory (`tests/conftest.py`), with stale session directories pruned after 6 hours. Guarded by `tests/test_pytest_isolation.py`, and verified by running two full suites concurrently. |

Do not describe branch protection or release-gate enforcement as completed
unless the API export or screenshot is attached to the release record.

## Alpha Sync Scope

Cloud sync is enabled for alpha only as an opt-in encrypted-blob service.
Clients upload and download AES-GCM ciphertext. The cloud API stores the blob,
size, ETag, timestamps, and account metadata; it must not parse, decrypt, log,
export, or return vault plaintext through metadata endpoints.

Conflict behavior is intentionally conservative:

- `PUT /api/v1/vault` accepts `If-Match` for stale-write protection.
- A stale `If-Match` returns `409` with the current ETag and keeps the newer
  blob intact.
- `X-Idempotency-Key` replays retry responses for the same write request.
- `GET /api/v1/vault/history` exposes previous revision metadata only, not
  revision contents.
- Browser clients may send `If-Match`, `If-None-Match`, and
  `X-Idempotency-Key` through CORS.

Not in alpha sync scope:

- server-side conflict merging;
- PostgreSQL/object-storage storage migration;
- cross-device real-time sync guarantees;
- recovery of data without the user's local master password or recovery code.

## Private Beta Metrics

Track at minimum:

- onboarding completion rate;
- vault unlock failure rate;
- recovery-code success/failure count;
- local API crash/error rate;
- admin login and MFA failure counts;
- license activation and heartbeat success/failure counts;
- support ticket volume by severity;
- encrypted-blob sync upload/download success, stale-write conflicts, and
  retry/idempotency outcomes.

## Release Sign-Off Record

Each release candidate requires explicit sign-off from:

- engineering owner;
- security owner;
- operations owner;
- product owner;
- legal/privacy owner.

Record for each signer:

- name or role;
- release tag;
- commit SHA;
- artifact checksum file;
- known issues accepted;
- date and time.

## Known Issues Template

- issue ID;
- severity;
- affected component;
- user impact;
- mitigation;
- owner;
- target fix version.
