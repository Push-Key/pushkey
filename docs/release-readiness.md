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
