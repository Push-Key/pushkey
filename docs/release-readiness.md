# Pushkey Release Readiness

Status: Phase 12 release-candidate control document.

## Release-Candidate Scope

The release candidate is limited to:

- local encrypted vault V3;
- desktop GUI and CLI;
- local web app served by the authenticated local API;
- MCP integration with scoped agent-token unlock;
- cloud license/device activation API;
- cloud admin API with individual admin accounts, roles, sessions, CSRF, MFA,
  audit attribution, and release-gated operations;
- browser and VS Code extensions only as beta clients unless their package/store
  gates pass.

Deferred features must not appear in launch claims:

- PostgreSQL/object-storage sync migration;
- distributed rate limiting;
- conflict-safe multi-device sync;
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

## Private Beta Metrics

Track at minimum:

- onboarding completion rate;
- vault unlock failure rate;
- recovery-code success/failure count;
- local API crash/error rate;
- admin login and MFA failure counts;
- license activation and heartbeat success/failure counts;
- support ticket volume by severity;
- sync reliability once conflict-safe sync is in scope.

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
