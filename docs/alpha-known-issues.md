# Alpha Known Issues

Issues surfaced by the pre-alpha adversarial review of `feat/pushkey-app`
that were triaged as acceptable for a constrained alpha and deferred, rather
than fixed before the tag. They are recorded here so the alpha release notes
and testers are not misled. The four major write-loss / DoS findings from the
same review were fixed before merge (commit "security: close four write-loss
and DoS gaps found in PR review").

Scope reminder: cloud sync is opt-in and experimental for alpha; the product
is local-first. Most items below live in the cloud or multi-writer paths that
a single-machine tester never exercises.

## Deferred — cloud admin/support paths (same class as a fixed finding)

- **Admin sessions and support tickets still use last-write-wins document
  writes.** The users/account store was moved to the row-locked
  `mutate_document` path, but `_load_admin_sessions`/`_save_admin_sessions` and
  `_load_tickets`/`_save_tickets` remain read-modify-write. Under concurrent
  admin activity a write can be lost. Low risk at alpha scale (few trusted
  admins, low concurrency). Follow-up: route these through `mutate_document`.
- **Admin session revocation can be undone by a concurrent request.**
  `_require_admin` re-saves the whole sessions document to stamp `last_used`, so
  a request in flight during `admin_revoke_sessions` can write back the
  pre-revocation snapshot and keep a revoked session alive until it expires
  (default TTL). `admin_disable` is unaffected. Fixed by the same
  `mutate_document` follow-up above.

## Deferred — cloud auth hardening

- **No rate limit on `request-reset` / `confirm-reset`.** Registration and
  login are throttled; the reset endpoints are not, so reset emails can be
  triggered repeatedly to any registered address and reset-token guessing is
  unthrottled (impractical against a 256-bit token, but free).
- **Password reset does not revoke outstanding JWTs.** After a reset, an
  attacker's existing bearer token stays valid until it expires (default 1h).
  There is no token revocation list.
- **Idempotency replay ignores the request body.** Reusing an
  `X-Idempotency-Key` with different vault bytes returns the cached prior
  success without writing the new body; the store already records
  `object_sha256`, so a future fix can 422 on payload mismatch. The shipped
  client does not send the header.

## Deferred — local `.env` handling regressions

- **`.env` plaintext backups are no longer pruned.** The consolidated
  `mutate_env_file` writes `.env.pushkey_backup_*` snapshots but never prunes
  to the most-recent few, so they accumulate in project directories. They are
  not covered by the `.env` gitignore entry the tool writes.
- **`.env` is read as strict UTF-8.** A single invalid byte in an existing
  `.env` now raises `UnicodeDecodeError` on the inject paths instead of being
  tolerated. Rare, but a regression from the prior `errors="ignore"` read.

## Deferred — CLI parity

- **`pushkey set-backup` skips the Pro-tier gate** that the MCP and local API
  enforce, and returns non-standard exit codes for "key not found" (130) and
  empty value (bare 1).
