# Health Sidecar V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a versioned, privacy-minimized, atomically published `health.json` v1 sidecar that all bundled local consumers validate consistently.

**Architecture:** Add a focused shared lock module and `pushkey_health.py` as the single owner of sidecar schema, bounded parsing, freshness, atomic publication, and invalidation. Vault writes provide a ciphertext revision so publishing and invalidation follow one lock order. The desktop loopback server and both extensions consume the strict v1 envelope while temporarily accepting normalized legacy data.

**Tech Stack:** Python 3.12, pytest, Windows/POSIX file locking, CustomTkinter, local HTTP server, Node built-in test runner, VS Code extension API, Chrome MV3.

---

## Controlling Documents

- Specification: `docs/superpowers/specs/2026-07-20-health-sidecar-v1-design.md`
- Status and resume record: `docs/IMPLEMENTATION_STATUS.md`
- Authorization dependency plan: `docs/superpowers/plans/2026-07-20-agentic-authorization-foundation.md`

## Execution Rules

1. Work only in `feat/agentic-auth-foundation`.
2. Keep `pushkeydev <pushkeydev@gmail.com>` as the Git identity.
3. Use TDD: write the narrow failing test, prove RED, implement, prove GREEN.
4. Maintain this lock order whenever both state domains are needed: process-local vault lock, `.vault.lock`, then `.health.lock`.
5. Do not publish secret values, paths, projects, notes, timestamps, token material, or arbitrary vault metadata.
6. Do not begin CP2 until CP1 passes Task 8 and the status document is updated.

## File Map

- Create: `pushkey_locking.py` and `tests/test_locking.py`.
- Create: `pushkey_health.py` and `tests/test_health_sidecar.py`.
- Create: `vscode-pushkey/health-contract.js` and `vscode-pushkey/test/health-contract.test.js`.
- Create: `browser-pushkey/health-contract.js` and `browser-pushkey/test/health-contract.test.js`.
- Modify: `pushkey_vault.py`, `pushkey.py`, `pushkey_cli.py`, `pushkey_mcp.py`, `pushkey_local_api.py`.
- Modify: `vscode-pushkey/extension.js`, `browser-pushkey/background.js`, `browser-pushkey/popup.js`.
- Modify: `pyproject.toml`, `build_exe.py`, focused tests, and CP1 documentation.

### Task 1: Persist CP1 Handoff And Build The Shared Lock

**Files:**
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Create: `pushkey_locking.py`
- Create: `tests/test_locking.py`
- Modify: `pyproject.toml`
- Modify: `build_exe.py`

- [x] **Step 1: Record CP1 as in progress**

Update `docs/IMPLEMENTATION_STATUS.md` with the active commit, CP1 task list, and the fact that implementation begins only after the spec and this plan are approved.

- [x] **Step 2: Write failing lock tests**

Cover two Python processes holding one adjacent lock path, bounded timeout, release after exception, and both Windows and POSIX code paths.

```python
def test_second_process_times_out_while_first_holds_lock(lock_path):
    with hold_lock_in_child(lock_path):
        with pytest.raises(FileLockTimeout):
            with bounded_file_lock(lock_path, timeout_seconds=0.1):
                pass
```

- [x] **Step 3: Run lock tests and verify RED**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_locking.py -v
```

Expected: FAIL because `pushkey_locking` does not exist.

- [x] **Step 4: Implement the bounded lock**

Expose:

```python
class FileLockTimeout(RuntimeError): ...

@contextmanager
def bounded_file_lock(path: Path, *, timeout_seconds: float = 5.0,
                      poll_seconds: float = 0.05): ...
```

Use a one-byte lock with `msvcrt.locking(..., LK_NBLCK, 1)` on Windows and nonblocking `fcntl.flock` on POSIX. Use `time.monotonic()`; never delete a lock file owned by another process.

- [x] **Step 5: Run lock tests and verify GREEN**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_locking.py -v
```

Expected: PASS.

- [x] **Step 6: Add package metadata and commit**

```powershell
git add docs/IMPLEMENTATION_STATUS.md pushkey_locking.py tests/test_locking.py pyproject.toml build_exe.py
git commit -m "Add bounded shared file locking"
```

### Task 2: Implement Strict Health V1 Schema And Legacy Normalization

**Files:**
- Create: `pushkey_health.py`
- Create: `tests/test_health_sidecar.py`
- Modify: `tests/conftest.py`
- Modify: `pushkey_providers.py`
- Modify: `tests/test_providers.py`

- [x] **Step 1: Write failing v1 document tests**

Test the exact envelope, UTC `generated_at`, sorted compact encoding, valid empty `keys`, and omission of secret values and prohibited metadata.

```python
def test_build_health_document_exposes_only_allowed_fields():
    document = build_health_document(
        {"OPENAI_API_KEY": {"value": "sk-secret", "provider": "OpenAI",
                            "created": "2026-07-01T00:00:00Z",
                            "notes": "private"}},
        generated_at=utc("2026-07-20T12:00:00Z"),
    )
    assert document["keys"]["OPENAI_API_KEY"] == {
        "status": "healthy", "days_old": 19, "provider": "OpenAI"
    }
    assert "sk-secret" not in encode_health_document(document).decode()
```

- [x] **Step 2: Write failing malformed-input and legacy tests**

Cover duplicate keys, unknown fields, booleans used as integers, invalid names, invalid provider, invalid status, oversize bytes, unsupported version, mixed root, each normalization-table row, and legacy mtime-derived `generated_at`.

- [x] **Step 3: Run schema tests and verify RED**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_health_sidecar.py -k "schema or legacy or privacy" -v
```

Expected: FAIL because `pushkey_health` does not exist.

- [x] **Step 4: Implement pure schema APIs**

Implement `build_health_document`, `validate_health_document`, `encode_health_document`, and `decode_health_document`. Refactor `pushkey_providers` with an injectable-time health-policy helper while preserving existing public behavior; call that helper rather than duplicating GUI thresholds. Import `pushkey_shared as _s` only for paths, and raise stable health reason codes without source values.

- [x] **Step 5: Implement freshness validation**

Enforce the 26-hour maximum age and five-minute future skew. Legacy callers supply final file mtime. Treat stale and clock-invalid documents as unavailable, not empty or healthy.

- [x] **Step 6: Run schema tests and verify GREEN**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_health_sidecar.py -k "schema or legacy or privacy or freshness" -v
```

Expected: PASS.

- [x] **Step 7: Commit schema ownership**

```powershell
git add pushkey_health.py pushkey_providers.py tests/test_health_sidecar.py tests/test_providers.py tests/conftest.py
git commit -m "Add strict health sidecar v1 schema"
```

### Task 3: Add Atomic Publication, Revision Checks, And Invalidation

**Files:**
- Modify: `pushkey_health.py`
- Modify: `pushkey_vault.py`
- Modify: `pushkey.py` and `pushkey_local_api.py` for opaque encrypted-vault replacement invalidation and safe boundary handling.
- Modify: `tests/test_health_sidecar.py`
- Modify: `tests/test_vault_crypto.py`
- Modify: `tests/test_ui_helpers.py` and `tests/test_local_api.py`

**Scope note:** Task 3 was expanded during review to cover GUI recovery reset and local API encrypted backup import/rekey boundaries. These opaque replacement paths must invalidate the sidecar while preserving the established vault-then-health lock ordering and must report safe boundary failures without leaving an unlocked stale session. Normal plaintext-aware publication integration remains Task 4.

- [x] **Step 1: Write failing filesystem tests**

Cover 1 MiB bound, unique temporary files, interruption before replacement, write/flush/replace/verification failure, symlink destination, symlink parent, symlink lock path, POSIX `0600` enforcement, Windows junction/reparse behavior with explicit privilege-sensitive skips, process concurrency, revision mismatch before and after `.health.lock`, and opaque import invalidation.

- [x] **Step 2: Run atomic-publication tests and verify RED**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_health_sidecar.py -k "write or lock or replace or invalidation or concurrent" -v
```

Expected: FAIL because sidecar publication is not implemented.

- [x] **Step 3: Refactor vault locking without changing vault behavior**

Make `pushkey_vault` use `bounded_file_lock(_s.VAULT_DIR / ".vault.lock")`. Expose narrowly scoped internal contexts for the established lock order; do not let callers acquire `.health.lock` before vault locks.

- [x] **Step 4: Implement atomic sidecar write**

Use an existing directory resolved through `pushkey_shared`, reject links/reparse points as specified, create a unique same-directory temporary file, flush and fsync, atomically replace, read back through the bounded strict reader, and fsync the parent where supported.

- [x] **Step 5: Bind publishing to the encrypted vault revision**

After a successful plaintext-aware vault write, use the SHA-256 ciphertext revision attached to `VaultData`. Reacquire vault locks, verify revision before and after health-lock acquisition, then publish. Raise `health_vault_changed` rather than writing an obsolete snapshot.

- [x] **Step 6: Implement opaque replacement invalidation**

For encrypted backup import and every other direct encrypted-vault replacement, retain vault locks, acquire `.health.lock`, remove only `health.json`, verify absence, and fsync the parent. A subsequent unlock repopulates the sidecar.

- [x] **Step 7: Run focused tests and verify GREEN**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_locking.py tests\test_health_sidecar.py tests\test_vault_crypto.py -v
```

Expected: PASS with only justified platform skips.

- [x] **Step 8: Commit safe publication**

```powershell
git add pushkey_locking.py pushkey_health.py pushkey_vault.py tests/test_locking.py tests/test_health_sidecar.py tests/test_vault_crypto.py
git commit -m "Publish health sidecar atomically"
```

### Task 4: Integrate Desktop, CLI, MCP, Local API, And Loopback HTTP

**Compliance closure:** Commit `3ded3db` completes the Task 4 review follow-up.
The Local API uses the stable `X-Pushkey-Warning: health_publication_failed`
response header for post-save publication failures so existing response bodies,
including `204` responses, remain compatible. Loopback contract tests now prove
the full unavailable-input and method-rejection behavior.

**Files:**
- Modify: `pushkey.py`
- Modify: `pushkey_cli.py`
- Modify: `pushkey_mcp.py`
- Modify: `pushkey_local_api.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mcp.py`
- Modify: `tests/test_local_api.py`
- Modify: `tests/test_health_sidecar.py`

- [x] **Step 1: Write failing integration tests**

Cover every plaintext-aware save path publishing v1, safe warning on publication failure, opaque backup import invalidation, successful unlock republish, and no test profile escape.

- [x] **Step 2: Write failing loopback HTTP tests**

Cover valid v1 response, valid empty snapshot, fixed 503 unavailable body for missing, malformed, stale, future-skewed, and oversized input, exact content type, no-store, nosniff, exact content length, no wildcard CORS, and rejection of non-GET methods.

- [x] **Step 3: Run integration tests and verify RED**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_health_sidecar.py tests\test_cli.py tests\test_mcp.py tests\test_local_api.py -k "health or backup" -v
```

Expected: FAIL because callers still use the GUI-only writer or raw file endpoint.

- [x] **Step 4: Replace the GUI-only writer**

Remove the old inline `write_health_sidecar` implementation. On GUI login and save, use the shared owner. Schedule a six-hour refresh only while the unlocked desktop session exists; cancel it on lock and shutdown.

- [x] **Step 5: Integrate non-GUI mutation paths**

Use the shared post-save hook for CLI, MCP, and local API mutations. Return only `health_publication_failed` or another stable safe warning, never a secret name or raw exception.

- [x] **Step 6: Harden the loopback health server**

Serve only validated canonical v1 bytes. Return a fixed 503 JSON body for unavailable data. Remove `Access-Control-Allow-Origin: *` and add the required response headers.

- [x] **Step 7: Run integration tests and verify GREEN**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_health_sidecar.py tests\test_cli.py tests\test_mcp.py tests\test_local_api.py -k "health or backup" -v
```

Expected: PASS.

- [x] **Step 8: Commit cross-interface integration**

```powershell
git add pushkey.py pushkey_cli.py pushkey_mcp.py pushkey_local_api.py tests/test_health_sidecar.py tests/test_cli.py tests/test_mcp.py tests/test_local_api.py
git commit -m "Integrate versioned health sidecar"
```

### Task 5: Update The VS Code Consumer

**Files:**
- Create: `vscode-pushkey/health-contract.js`
- Create: `vscode-pushkey/test/health-contract.test.js`
- Modify: `vscode-pushkey/extension.js`
- Modify: `vscode-pushkey/package.json`
- Modify: `vscode-pushkey/README.md`

- [ ] **Step 1: Add failing Node contract tests**

Use `node --test` to cover v1 parsing, legacy fallback, legacy file-mtime freshness, 26-hour expiry, five-minute future skew, malformed JSON, mixed legacy/envelope shape, unknown versions, unknown status, 1 MiB bound, missing-file state, valid empty document, atomic watcher replacement, and watcher reattachment after the Pushkey directory appears.

- [ ] **Step 2: Run VS Code contract tests and verify RED**

```powershell
Set-Location vscode-pushkey
node --test test/health-contract.test.js
```

Expected: FAIL because the parser module does not exist.

- [ ] **Step 3: Implement bounded parser and watcher behavior**

Read at most 1 MiB plus one byte. Accept strict v1 or normalized legacy only. Clear cached health when unavailable. Debounce directory notifications, retry transient replacement reads, and reattach the watcher when the Pushkey directory appears.

- [ ] **Step 4: Keep hover content untrusted**

Do not set `MarkdownString.isTrusted = true` for sidecar-derived content. Ensure malformed fields cannot call string methods unsafely.

- [ ] **Step 5: Run tests and commit**

```powershell
Set-Location vscode-pushkey
node --test test/health-contract.test.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
git add vscode-pushkey
git commit -m "Validate health sidecar in VS Code"
```

### Task 6: Update The Browser Extension Consumer

**Files:**
- Create: `browser-pushkey/health-contract.js`
- Create: `browser-pushkey/test/health-contract.test.js`
- Modify: `browser-pushkey/background.js`
- Modify: `browser-pushkey/popup.js`
- Modify: `browser-pushkey/README.md`

- [ ] **Step 1: Add failing Node contract tests**

Cover v1 parsing, legacy fallback, 26-hour expiry, five-minute future skew, unavailable HTTP result, malformed document, oversized input, mixed legacy/envelope shape, unsupported version, unknown status, aggregate counts, and a key name containing markup-like text.

- [ ] **Step 2: Run browser contract tests and verify RED**

```powershell
Set-Location browser-pushkey
node --test test/health-contract.test.js
```

Expected: FAIL because the parser module does not exist.

- [ ] **Step 3: Implement bounded normalized response handling**

The background worker validates each response before storage and stores only normalized keys, counts, schema version, and poll time. Unavailable data clears stored health rather than retaining stale metadata.

- [ ] **Step 4: Replace unsafe dynamic HTML rendering**

Keep static extension-owned offline templates if needed. Create key rows with `document.createElement` and assign all sidecar-derived names with `textContent`; map status to a fixed allowlist of CSS classes.

- [ ] **Step 5: Run tests and commit**

```powershell
Set-Location browser-pushkey
node --test test/health-contract.test.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
git add browser-pushkey
git commit -m "Harden browser health consumer"
```

### Task 7: Update Packaging, Documentation, And Resumable Status

**Files:**
- Modify: `pyproject.toml`
- Modify: `build_exe.py`
- Modify: `docs/PRODUCTION_READINESS_PLAN.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/superpowers/plans/2026-07-20-agentic-authorization-foundation.md`
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: extension READMEs

- [ ] **Step 1: Add packaging tests**

Add tests that import `pushkey_locking` and `pushkey_health`; verify each appears independently in both `pyproject.toml` and `build_exe.py`.

- [ ] **Step 2: Update contract documentation**

Record the v1 envelope, local-sensitive metadata classification, temporary legacy compatibility, freshness limits, no wildcard CORS, CP1 evidence, and exact resume point. Update the authorization implementation plan to state that CP1 introduced `pushkey_locking.py`; CP3 extends and reuses it rather than recreating the module. Do not mark extension marketplace or remote-environment work complete.

- [ ] **Step 3: Validate text and documentation**

```powershell
$bad = rg -n "TODO|TBD|PLACEHOLDER|\\x{00E2}|\\x{2014}|\\x{2013}" docs README.md SECURITY.md vscode-pushkey\README.md browser-pushkey\README.md
if ($LASTEXITCODE -eq 0) { $bad; throw "invalid documentation text" }
if ($LASTEXITCODE -ne 1) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: no placeholders, mojibake, or invalid punctuation.

- [ ] **Step 4: Commit documentation and packaging**

```powershell
git add pyproject.toml build_exe.py docs README.md SECURITY.md vscode-pushkey/README.md browser-pushkey/README.md
git commit -m "Document health sidecar v1 checkpoint"
```

### Task 8: Verify CP1 And Record The Handoff

**Files:**
- Modify: `docs/PRODUCTION_READINESS_PLAN.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

- [ ] **Step 1: Run focused Python suites**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest tests\test_locking.py tests\test_health_sidecar.py tests\test_vault_crypto.py tests\test_cli.py tests\test_mcp.py tests\test_local_api.py -v
```

Expected: PASS with only explicit platform skips.

- [ ] **Step 2: Run extension contract suites**

```powershell
Set-Location vscode-pushkey
node --test test/health-contract.test.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..\browser-pushkey
node --test test/health-contract.test.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
```

Expected: PASS.

- [ ] **Step 3: Run the complete Python suite**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -m pytest -q --durations=30 --durations-min=0.1
```

Expected: all tests pass with only documented platform skips.

- [ ] **Step 4: Build both frontend applications**

```powershell
Set-Location web
npm run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..\web-app
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run integrity
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
```

Expected: all commands pass.

- [ ] **Step 5: Verify package and executable inclusion**

```powershell
C:\Users\aware\bots\pushkey\.venv\Scripts\python.exe -c "import pushkey_locking, pushkey_health"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
rg -n '"pushkey_locking"|"pushkey_health"' pyproject.toml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
rg -n "pushkey_locking|pushkey_health" build_exe.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: both modules are importable and declared in both build surfaces.

- [ ] **Step 6: Build packaged executables from a clean cache**

Follow the repository icon/build policy. Validate cleanup paths first, rebuild with `build_exe.py`, run `dist\pushkey-cli.exe --help`, and do not copy binaries to the desktop.

- [ ] **Step 7: Record CP1 evidence and completion**

Update the CP1 evidence row in `docs/PRODUCTION_READINESS_PLAN.md`. Update `docs/IMPLEMENTATION_STATUS.md` with exact test counts, HEAD commit, CP1 completion, and CP2 as the next action.

- [ ] **Step 8: Commit and verify final CP1 state**

```powershell
git add docs/PRODUCTION_READINESS_PLAN.md docs/IMPLEMENTATION_STATUS.md
git commit -m "Record CP1 health sidecar completion"
git status --short --branch
git log -12 --oneline --decorate
```

Expected: clean branch, focused commits, and a resumable Markdown handoff.

## CP1 Completion Report

After Task 8, report:

1. Completed interfaces and security guarantees.
2. Focused, full-suite, extension, build, and packaging evidence.
3. Branch, HEAD, and clean or dirty status.
4. Exact production checklist numerator, denominator, and percentage.
5. The remaining Phase 1 and Phase 9 extension work not completed by CP1.
6. CP2 as the next independently testable action.
