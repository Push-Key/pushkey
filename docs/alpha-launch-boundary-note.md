# Pushkey Alpha Launch Boundary Note

Date: 2026-07-23

This note records the current alpha launch boundary for Pushkey.

## Decision

Pushkey may be treated as sellable/evaluable alpha with constrained claims,
but it is not production or GA ready.

Alpha release is invite-only and unsigned builds are acceptable for this
phase, provided every distributed artifact carries a checksum, version tag,
and commit SHA and is shipped only through an official channel.

## Verified Alpha Scope

- Local encrypted vault V3.
- Desktop GUI and CLI for local secret management.
- Local web app through the authenticated localhost API.
- MCP integration using scoped agent tokens.
- Admin/license portal with individual admin accounts, roles, sessions, CSRF,
  MFA, audit attribution, and abuse/rate-limit alerts.
- Cloud account/vault endpoints only as encrypted-blob alpha sync.

## Explicit Non-Claims

Do not claim the following for alpha:

- independent security review complete;
- penetration testing complete;
- distributed Redis/API-gateway rate limiting;
- PostgreSQL/object-storage sync cutover;
- signed Windows/macOS artifacts;
- production monitoring, backup, rollback, signing, or external review for
  full production/GA readiness.

## Current Limitations

- Alert-delivery proof is now captured in the accountable-operator inbox.
- GitHub branch protection and release-gate enforcement are now configured in
  repository settings.
- Production backups, rollback, signing, and external review remain post-alpha
  / GA work.
- The current completion tracker shows 320/327 alpha-launch items complete
  (97.9%). The remaining four are operator actions: CI green on the release
  commit, managed database backups, an uptime check, and a new alpha tag
  carrying the vault write-loss fix.
- 18 public-beta / GA gates (signing, hosted backup and rollback drills,
  independent review, penetration test) and 3 post-launch review items are
  deferred and counted in separate buckets, not against alpha readiness.

## Recent Verification

- `SMTP/IMAP alert-delivery proof to the accountable operator inbox` ->
  confirmed.
- `GitHub release v0.1.0-alpha` -> official alpha bundle published with
  `build.tar.gz`, `CHECKSUMS.txt`, and `CHECKSUMS.txt.sha256`.
- `GitHub branch protection and release-gate settings` -> configured through
  repository settings API and recorded in the handoff checklist.
- `python -m pytest -q` -> 475 passed, 1 skipped.
- `npm --prefix web-app run lint` -> passed.
- `npm --prefix web-app run build` -> passed and generated the integrity
  manifest.
- `npm --prefix web run lint` -> passed.
- `npm --prefix web run build` -> passed.
- `scripts/package_upgrade_smoke.py --wheel dist/pushkey-2.1.0-py3-none-any.whl`
  -> passed.
- `scripts/npm_package_smoke.py` -> passed.

## Accepted Risks

- Destructive restore and rollback drills remain deferred until the production
  operations phase.
- Independent security review, penetration testing, and signed-artifact
  installation confirmation remain Public Beta gates.

## Evidence Basis

- `docs/100_PERCENT_COMPLETION_TASKLIST.md`
- `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`
- `docs/ALPHA_SELLABLE_READINESS_CHECKLIST.md`
- `docs/PRODUCTION_READINESS_PLAN.md`
- `docs/ops-readiness.md`
- `scripts/roadmap_progress.py`
