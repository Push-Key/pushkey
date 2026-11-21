# Health Sidecar V1 Design

**Status:** Approved for implementation planning
**Date:** 2026-07-20
**Production checkpoint:** CP1
**Controls:** `health.json` filesystem sidecar, loopback health response, VS Code
and browser extension consumers

## Purpose

Pushkey currently writes an unversioned `~/.pushkey/health.json` object from the
desktop GUI. The VS Code extension reads that file directly, and the browser
extension reads the same bytes from an unauthenticated loopback HTTP endpoint.
The current path has no schema version, bounded parser, shared publication
owner, concurrency lock, or explicit privacy contract.

CP1 establishes a versioned, non-secret health sidecar that every local
consumer can validate consistently. It preserves secret-name matching for
local extensions while reducing the published metadata to the minimum needed
for health decoration.

This specification is an independent prerequisite for the agentic
authorization foundation. It does not implement agent tokens, permissions,
approvals, execution, remote access, or secret reveal.

## Goals

1. Define one explicit version 1 schema.
2. Keep secret values and unrelated vault metadata out of the sidecar.
3. Publish complete snapshots atomically and durably where the platform allows.
4. Make publication consistent across normal GUI, CLI, MCP, and local API vault
   saves.
5. Make missing, malformed, unsupported, stale, and valid-empty states
   distinguishable.
6. Preserve a bounded legacy-read window while all bundled consumers migrate.
7. Remove browser-origin access to key-level health metadata.
8. Add executable contract, security, concurrency, and packaging verification.

## Non-Goals

- Encrypting the sidecar.
- Publishing secret values, value prefixes, notes, project names, or paths.
- Remote health access.
- Replacing the authenticated local API `/api/health` contract.
- Supporting arbitrary third-party sidecar schemas.
- Making sidecar publication part of encrypted-vault transaction success.
- Claiming Remote SSH, WSL, container, marketplace, or browser-store readiness.

## Current Problems

The current writer in `pushkey.py`:

- is owned by the GUI rather than a shared module;
- uses a fixed `health.tmp` filename;
- has no cross-process lock;
- suppresses every publication error;
- publishes timestamps and usage metadata not required by extensions;
- resolves `HEALTH_FILE` through an import-time alias that bypasses test-path
  isolation; and
- runs only on selected GUI flows, so other successful vault mutations can
  leave stale health data.

The current consumers:

- accept arbitrary JSON shapes and sizes;
- default malformed or missing statuses toward healthy behavior;
- do not distinguish a valid empty vault from unavailable data;
- do not understand schema versions;
- retain stale VS Code decorations when the file disappears;
- serve raw unvalidated bytes over HTTP;
- send `Access-Control-Allow-Origin: *`; and
- insert key-controlled browser content through `innerHTML`.

## Trust And Privacy Boundary

`health.json` is derived local metadata. It is not secret plaintext, but secret
names and provider identifiers can reveal operational details. The sidecar is
therefore classified as **local-sensitive metadata**, not public internet data.

Version 1 may contain only:

- schema version;
- snapshot generation time;
- eligible secret names;
- normalized health status;
- non-negative age in whole days or null; and
- a bounded provider identifier or null.

Version 1 must never contain:

- secret values or value fragments;
- backup or historical values;
- master passwords, recovery codes, token plaintext, token hashes, or wrapped
  keys;
- notes or arbitrary user-authored metadata;
- project IDs, project names, filesystem paths, Git remotes, or environments;
- created, rotated, first-used, or last-used timestamps;
- rotation counts;
- command output, policy details, authorization records, or audit payloads; or
- cloud, license, device, or account identifiers.

The file should use owner-only permissions where supported. Failure to tighten
permissions follows the platform contract below. It does not roll back an
already committed encrypted-vault mutation.

## Version 1 Schema

The encoded document is UTF-8 JSON:

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-20T12:34:56Z",
  "keys": {
    "STRIPE_TEST_KEY": {
      "status": "warning",
      "days_old": 67,
      "provider": "Stripe"
    }
  }
}
```

### Root Contract

| Field | Type | Required | Rule |
|---|---|---:|---|
| `schema_version` | integer | yes | Exactly `1`; booleans are not integers. |
| `generated_at` | string | yes | UTC RFC 3339, whole seconds, `Z` suffix. |
| `keys` | object | yes | Zero through 10,000 records. |

Unknown root fields are rejected. Duplicate JSON object keys are rejected at
every level.

### Secret Record Contract

Each `keys` property name is an eligible environment-variable name matching
`^[A-Za-z_][A-Za-z0-9_]{0,127}$` and is at most 128 ASCII bytes.

| Field | Type | Required | Rule |
|---|---|---:|---|
| `status` | string | yes | `healthy`, `warning`, `critical`, or `unknown`. |
| `days_old` | integer or null | yes | `0..365000`; booleans are rejected. |
| `provider` | string or null | yes | `1..64` printable ASCII bytes or null. |

Unknown record fields are rejected. Non-mapping vault records and ineligible
secret names are omitted by the builder because they cannot be matched safely
to `.env` entries. A valid vault with no eligible records produces a valid
empty `keys` object.

### Size And Encoding

- Maximum encoded size: 1,048,576 bytes.
- Canonical producer encoding: UTF-8, sorted keys, compact separators, one
  trailing newline.
- JSON nesting is fixed by the schema.
- Non-finite numbers are rejected.
- Readers read at most the limit plus one byte and reject oversized input
  before parsing.

## Health Calculation

The builder uses the existing provider health policy as the single source of
truth. It must not maintain a second threshold implementation in the GUI.

For each eligible vault record:

1. Determine the effective date from `rotated` or `created` and `first_used`
   using the existing policy semantics.
2. Determine the provider-specific rotation threshold, defaulting to 90 days.
3. Emit `critical` when age is strictly greater than the threshold.
4. Emit `warning` when age is strictly greater than 67 percent of the
   threshold.
5. Emit `healthy` otherwise.
6. Emit `unknown` and `days_old: null` when required date data is missing,
   invalid, non-finite, or in the future.

`days_old` is an integer and never negative. Provider data that does not meet
the bounded public identifier contract is emitted as null.

## Module Ownership

Create `pushkey_health.py` as the sole owner of the sidecar contract. It imports
`pushkey_shared as _s` and resolves `_s.HEALTH_FILE` at call time.

Public API:

```python
class HealthSidecarError(RuntimeError): ...
class HealthSchemaError(HealthSidecarError): ...
class HealthPathError(HealthSidecarError): ...
class HealthBusyError(HealthSidecarError): ...
class HealthUnavailableError(HealthSidecarError): ...

def build_health_document(
    vault: Mapping[str, Mapping[str, object]],
    *,
    generated_at: datetime | None = None,
) -> dict: ...

def validate_health_document(document: object) -> dict: ...

def encode_health_document(document: object) -> bytes: ...

def decode_health_document(
    raw: bytes,
    *,
    allow_legacy: bool = True,
    legacy_generated_at: datetime | None = None,
) -> dict: ...

def read_health_sidecar(
    path: Path | None = None,
    *,
    allow_legacy: bool = True,
    now: datetime | None = None,
) -> dict: ...

def write_health_sidecar(
    vault: Mapping[str, Mapping[str, object]],
    path: Path | None = None,
    *,
    generated_at: datetime | None = None,
    expected_vault_revision: bytes,
) -> dict: ...

def invalidate_health_sidecar(path: Path | None = None) -> None: ...
```

The module raises stable sanitized error codes. It never logs vault data or
includes a secret name in an exception message.

The adjacent cross-process locking primitive may be implemented in the shared
`pushkey_locking.py` module planned for the authorization foundation. If CP1
introduces that module first, the authorization plan changes its CP3 step from
creation to extension and reuses the same primitive.

`decode_health_document` validates bytes without applying filesystem freshness.
Legacy bytes require a `legacy_generated_at` argument when callers need a
normalized v1 envelope. `read_health_sidecar` obtains that value from the
opened file's final metadata and applies the freshness contract.

## Freshness Contract

A v1 snapshot is current when:

- `generated_at` is no more than 26 hours before the reader's UTC clock; and
- `generated_at` is no more than five minutes after the reader's UTC clock.

Older snapshots are `health_stale`. Snapshots farther in the future are
`health_clock_invalid`. Both are unavailable states: VS Code clears health
decorations, the browser reports unavailable, and the loopback endpoint returns
HTTP 503. Consumers never continue showing a previously accepted snapshot
after a freshness failure.

For a legacy file, the final file modification time becomes the normalized
`generated_at`. A missing, non-finite, out-of-range, or future modification time
is unavailable. Legacy bytes alone have no freshness claim; tests of
`decode_health_document` must supply the explicit legacy generation time.

While the desktop vault remains unlocked, it republishes health at least every
six hours and cancels that timer on lock or shutdown. Unlock and successful
plaintext-aware saves also republish. This keeps an active desktop snapshot
within the 26-hour window without writing continuously. CLI, MCP, or local API
publication remains current for 26 hours unless another successful save or
desktop unlock refreshes it.

## Atomic Publication

Publication uses this sequence:

1. Build, validate, and encode the complete document in memory.
2. Acquire the process-local vault write lock and then `.vault.lock`.
3. Compare the current encrypted vault revision with
   `expected_vault_revision`; abort with `health_vault_changed` on mismatch.
4. Ensure the parent directory exists.
5. Reject a parent directory, destination, or lock path that is a symbolic link
   or Windows reparse point. Platform checks fail closed when identity cannot
   be established.
6. Acquire the adjacent `.health.lock` with a bounded timeout while retaining
   the vault locks.
7. Revalidate the vault revision, parent, and destination identities after
   health-lock acquisition.
8. Create a unique temporary file in the destination directory with
   `mkstemp` and restrictive permissions.
9. Write bounded bytes, flush, and `fsync` the file.
10. Revalidate the vault revision, parent, destination, and temporary file
    identities.
11. Atomically replace `health.json`.
12. Reopen with a bounded read and validate the exact v1 document.
13. `fsync` the parent directory where supported.
14. Remove only the exact temporary file owned by this invocation.
15. Release locks in reverse order.

Concurrent writers may publish in either order, but readers must observe one
complete valid snapshot. A failed write before replacement preserves the prior
snapshot. A post-replacement verification failure is reported and never
silently described as success.

Every operation that publishes or invalidates health uses one lock order:

1. process-local vault write lock;
2. cross-process `.vault.lock`;
3. cross-process `.health.lock`.

No health operation acquires these locks in reverse order. This order and the
two vault-revision comparisons prevent an obsolete in-memory snapshot from
publishing after a newer encrypted-vault replacement.

### Platform Filesystem Guarantees

On POSIX:

- temporary, lock, and final sidecar files are mode `0600`;
- a failure to create or retain mode `0600` fails publication;
- symbolic-link checks use non-following metadata operations; and
- parent-directory `fsync` is required when the platform supports opening a
  directory descriptor.

On Windows:

- the sidecar, temporary file, and lock inherit the ACL of the existing
  user-profile `.pushkey` directory;
- CP1 does not rewrite ACLs or claim that `chmod` creates a POSIX-equivalent
  owner-only ACL;
- paths are inspected for `FILE_ATTRIBUTE_REPARSE_POINT` before opening and
  again before replacement;
- existing reparse destinations, parent directories (the sidecar's own
  directory, not directories above it), or lock paths fail publication; and
- inability to establish reparse status fails publication.

The sidecar is local-sensitive derived metadata, not a security boundary
against another malicious process already running as the same operating-system
user. Standard path APIs cannot eliminate every same-account time-of-check to
time-of-use race on both platforms. CP1 guarantees bounded writes, unique
temporary files, adjacent locking, no intentional link traversal at the paths
Pushkey owns (the sidecar's directory, the sidecar, and its lock; links above
that directory belong to the operating system or the user's layout and are not
checked), repeated
identity checks, and preservation against ordinary crashes and concurrent
Pushkey writers. Tests and documentation must not claim stronger hostile-user
isolation.

## Publication Integration

Normal plaintext-aware vault saves call the sidecar publisher after the
encrypted vault commit succeeds. The save returns or attaches the SHA-256
revision of the committed encrypted vault bytes. Publication then reacquires
the vault locks in the global order, verifies that exact revision before and
after acquiring `.health.lock`, and only then replaces the sidecar. The
sidecar remains derived rather than part of encrypted-vault transaction
success.

Publication failure follows these rules:

- the encrypted vault mutation remains successful;
- the caller receives or records a sanitized `health_publication_failed`
  warning;
- GUI flows remain usable and write a sanitized audit/log event;
- CLI, MCP, and local API responses include a safe warning where their existing
  response contract permits it; and
- no exception or warning contains a secret name or value.

Encrypted-byte replacement paths that cannot inspect the imported vault must
invalidate the existing sidecar before declaring import complete. Invalidation
occurs while retaining the vault locks after the encrypted replacement and
then acquiring `.health.lock` in the global order. It removes `health.json`,
flushes the parent directory where supported, and releases the locks only
after absence is verified. An older publisher either completed before the
replacement and is then invalidated, or observes a revision mismatch and
cannot recreate stale names. Successful next unlock republishes v1.

Rekey and recovery-slot updates that preserve vault contents do not require a
new health snapshot unless they already have the decrypted vault available.

## Reader And Compatibility Contract

Bundled readers support:

1. strict version 1 envelopes; and
2. the legacy unversioned top-level record map for one documented compatibility
   window.

Legacy detection is allowed only when the root is an object and none of the
reserved envelope fields `schema_version`, `generated_at`, or `keys` is
present. Legacy input uses this exact normalization:

| Legacy input | Normalized v1 behavior |
|---|---|
| More than 10,000 root entries | Reject the whole document. |
| Ineligible or overlong secret name | Omit that entry. |
| Non-object record | Reject the whole document. |
| Missing or invalid `status` | Emit `unknown`. |
| Valid `healthy`, `warning`, or `critical` status | Preserve it. |
| `days_old` integer in `0..365000` | Preserve it. |
| Missing, boolean, invalid, negative, or excessive `days_old` | Emit null. |
| Printable ASCII `provider` of 1 through 64 bytes | Preserve it. |
| Missing, invalid, or overlong `provider` | Emit null. |
| Current extra fields such as `category`, timestamps, or rotation count | Ignore them. |
| Any reserved envelope root field | Reject as a mixed shape. |

The normalized `generated_at` comes only from the file modification time and
must pass the freshness contract. Normalized output is validated against the
strict v1 schema before use. An all-ineligible but otherwise structurally valid
legacy map becomes a valid empty snapshot.

Unknown schema versions, mixed legacy/envelope shapes, malformed JSON,
oversized input, duplicate keys, or invalid v1 records are unavailable states.
Readers must not guess a future schema.

Legacy support is removed only after the shipped VS Code and browser extension
versions that understand v1 have passed packaging and install verification.

## Filesystem Consumer Behavior

The VS Code extension:

- resets in-memory health to unavailable when the file is missing;
- reads with the same 1 MiB bound;
- validates v1 or legacy before replacing the last parsed state;
- treats unknown status as unknown rather than healthy;
- removes stale decorations when data becomes unavailable;
- watches the directory so atomic replacement remains visible;
- debounces watcher events and retries bounded transient replacement errors;
- reattaches its watcher when `~/.pushkey` is created after activation; and
- uses untrusted Markdown for hover text.

The extension never reads `vault.enc` or `.env` values.

## Loopback HTTP Contract

The desktop health server remains bound only to `127.0.0.1`. `GET /health`:

- calls the shared bounded reader;
- returns the canonical v1 envelope with HTTP 200 for valid data, including a
  valid empty snapshot;
- returns a small fixed JSON error with HTTP 503 for missing, malformed,
  oversized, unsupported, or transiently unreadable data;
- never returns raw unvalidated file bytes;
- sends `Content-Type: application/json; charset=utf-8`;
- sends `Cache-Control: no-store`;
- sends `X-Content-Type-Options: nosniff`;
- sends an exact `Content-Length`; and
- sends no `Access-Control-Allow-Origin` wildcard or reflected origin.

The browser extension keeps explicit loopback host permission and can fetch
from its service worker. Ordinary websites cannot read the response through
browser CORS APIs.

The server rejects non-GET methods. It does not add a remote bind option in
this milestone.

## Browser Extension Behavior

The browser extension:

- validates the v1 or legacy response before storage;
- stores only the normalized `keys` map, aggregate counts, schema version, and
  local poll timestamp;
- treats 503, parse failure, unsupported versions, and invalid records as
  unavailable;
- never defaults missing or unknown status to healthy;
- constructs key rows with `createElement`, `textContent`, and fixed CSS class
  mappings rather than `innerHTML`; and
- never renders provider or key-controlled text as markup.

The fixed offline and empty-state templates may use static HTML owned by the
extension, but no sidecar-derived content enters those templates.

## Error Semantics

Stable internal reason codes include:

- `health_missing`;
- `health_too_large`;
- `health_malformed_json`;
- `health_duplicate_field`;
- `health_unsupported_version`;
- `health_schema_invalid`;
- `health_stale`;
- `health_clock_invalid`;
- `health_vault_changed`;
- `health_path_unsafe`;
- `health_lock_timeout`;
- `health_write_failed`;
- `health_replace_failed`; and
- `health_verification_failed`.

Consumer-facing errors expose only availability state and safe operator
guidance. They do not include raw JSON, filesystem paths, secret names, or
record contents.

## Test Strategy

### Python Contract Tests

Create `tests/test_health_sidecar.py` covering:

- deterministic v1 construction and canonical encoding;
- 26-hour expiry, five-minute future skew, and six-hour desktop refresh;
- exact health threshold behavior and unknown dates;
- valid empty vault behavior;
- omission of ineligible records;
- absence of every prohibited field and supplied secret value;
- all field types, bounds, enums, unknown fields, and duplicate keys;
- unsupported versions and mixed legacy/envelope documents;
- legacy normalization and eventual compatibility warning;
- legacy modification-time freshness and every normalization-table row;
- 1 MiB and 10,000-record limits;
- bool-versus-int rejection and non-finite number rejection;
- test isolation through `pushkey_shared.HEALTH_FILE`;
- unique temporary files and cleanup;
- owner-only file mode where supported;
- file and directory flush failures;
- replace and post-write verification failures;
- prior-snapshot preservation before replacement;
- two synchronized processes publishing complete valid snapshots;
- publication racing encrypted replacement never restoring stale names;
- revision mismatch before and after health-lock acquisition;
- symlink destination rejection;
- symlink parent rejection; and
- Windows junction/reparse tests with explicit platform skips when privileges
  are unavailable.

### Integration Tests

Cover:

- successful GUI, CLI, MCP, and local API plaintext-aware saves publishing v1;
- encrypted backup import invalidating stale health;
- successful unlock republishing imported health;
- publication failure preserving successful vault mutation and returning only
  a safe warning;
- loopback HTTP 200, valid-empty, 503, headers, size bound, and no wildcard
  CORS; and
- no test touching the real user profile.

### Extension Tests

Add JavaScript tests for both bundled extensions covering:

- v1 and legacy parsing;
- malformed, oversized, mixed, and unsupported input;
- unknown status behavior;
- missing-file stale-state clearing;
- watcher replacement and reattachment;
- browser unavailable and valid-empty states;
- safe rendering of names containing markup-like text; and
- aggregate count correctness.

### Packaging Verification

- Add every new Python module to `pyproject.toml` and `build_exe.py`.
- Run focused tests, the complete Python suite, and extension tests.
- Build both PyInstaller executables from a clean cache.
- Package/install-test extensions remains a Phase 9 release gate unless the
  CP1 implementation plan explicitly includes it.

## Documentation Updates

Update:

- `docs/ARCHITECTURE.md` with ownership and trust boundaries;
- `docs/PRODUCTION_READINESS_PLAN.md` with CP1 evidence;
- `README.md` and extension READMEs with the v1 envelope and privacy language;
- `SECURITY.md` with local-sensitive metadata and loopback CORS behavior; and
- the agentic authorization plan so CP1 completion and any early shared locking
  work are reflected accurately.

Documentation must not describe secret names as harmless public data. It must
state that values never enter the sidecar.

## Exit Gate

CP1 is complete only when:

1. the v1 schema and privacy boundary are documented and executable;
2. all normal plaintext-aware vault save interfaces publish through the shared
   owner;
3. encrypted replacement invalidates stale health;
4. filesystem and HTTP consumers validate bounded input;
5. wildcard CORS and key-controlled browser `innerHTML` are removed;
6. concurrency, interruption, hostile path, malformed input, and compatibility
   tests pass;
7. packaging includes every new module;
8. the complete Python baseline remains green with only justified platform
   skips; and
9. the production roadmap records exact evidence without marking later
   extension-store gates complete.
