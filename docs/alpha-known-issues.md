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

## Deferred — cloud backend not deployed for alpha

The production cloud API (`pushkey_cloud_api.py`) is not deployed for the
local-first alpha: the documented Fly URL and the code-default host do not
resolve, and the managed Supabase project is on the Free plan (no managed
backups). Consequently the two cloud-ops roadmap items — managed database
backups and an external uptime check — are deferred to the public-beta gate;
there is no live service to back up or monitor yet. They return when the cloud
backend goes live. This does not affect testers: the alpha is the local CLI and
web app, and cloud sync is opt-in.

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

- **Env file backups moved out of the project.** Before Pushkey changes a
  project env file it copies the old one to
  `~/.pushkey/env-backups/<project id>/` and keeps the newest 3 per file. The
  copies are plaintext (so is the env file itself) and sit outside the
  project, so they cannot be committed. Old `.env.pushkey_backup_*` files from
  earlier versions are still ignored by the project's `.gitignore` but are not
  deleted automatically; delete them by hand.
- **`.env` is read as strict UTF-8.** The connect, sync and inject paths
  (CLI, local API, MCP and the desktop connect screens) refuse an env file with
  an invalid byte (`invalid_env_file`) and leave it untouched. The older
  `inject_env_file` helper in `pushkey.py` (used by its command-line inject)
  still reads strictly and can raise `UnicodeDecodeError`.

## Deferred — add-and-connect

Known limits of connecting keys to projects. None loses a key; they are listed
so testers are not surprised.

- **`.gitignore` coverage is checked against the project's root `.gitignore`
  only.** A nested `.gitignore` with a negation (for example `!.env.local` in a
  subfolder) is not seen. If git is missing, times out, or `git ls-files`
  fails, the file is treated as not tracked. A crashed write can leave a
  `.pushkey-*` temp file that holds a secret and is not ignored.
- **Edge cases in env file text.** A value ending in a backslash, written in
  double quotes, can make python-dotenv drop the whole file when a later line
  has a double quote. A variable with an unterminated quote can delete lines
  that the Next.js dotenv loader still reads as live. New lines use LF even in a
  CRLF file.
- **Backup names can collide.** `a/b` and `a__b` flatten to the same backup
  name.
- **A partial failure is reported per file.** Replacing a key rewrites every
  connected file in one pass. A file that fails says why (`written: false`
  with a reason), the connection stays, and `sync` retries it. After a partial
  failure the reply can list `synced: []` although some files were written.
- **`rotated` is a timestamp** (`%Y-%m-%dT%H:%M:%S`) on entries written by
  rotate, promote or connect; older entries keep a date. Readers accept both.
- **Windows file locking.** `config.json` replacement can fail with
  `PermissionError` while another program holds the file open, and the very
  first lock-file creation can race. Nothing is written in either case. A
  password unlock waits up to 5 seconds for the config lock, then continues
  without migrating.
- **Interactive shell.** Values typed in the shell are refused and never saved
  to history. A typed value that starts with `-` is not recognised as a value,
  and macOS libedit history can keep escaped lines. An `unrecognized arguments`
  error can echo part of an unquoted value (also true of the one-shot CLI).
- **One-time migration.** It copies the desktop's extra fields (such as `ci_*`
  and `github_*`) unfiltered, rewrites the vault even when there was nothing
  to move, and keeps `projects_legacy` forever. `ensure_migrated` runs on every
  master-password CLI command; its cost is unmeasured.
- **Disconnect leaves the line in the file.** `DELETE /api/connections` and the
  desktop and web "Disconnect" stop future writes but never remove the line
  already written. `POST /api/connections/sync` with no key also syncs
  internal `_`-prefixed entries that have connections.
- **Desktop.** Changing the master password, or importing a vault, while
  another Pushkey process saved can lose that change until the next unlock.

## Deferred — CLI parity

- **`pushkey set-backup` skips the Pro-tier gate** that the MCP and local API
  enforce, and returns non-standard exit codes for "key not found" (130) and
  empty value (bare 1).
