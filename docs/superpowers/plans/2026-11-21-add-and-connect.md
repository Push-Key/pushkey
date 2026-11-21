# Add & Connect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One "add and connect" action in every entry point (CLI, MCP, web app, desktop): a key is saved in the vault, connected to a registered project folder, written into that project's env file under the variable the project reads, and kept up to date when the key is replaced.

**Architecture:** Connections live on each vault entry (`vault[KEY]["connections"]`, encrypted with the master password) next to the existing `projects` allowlist. Three new framework-free modules carry the logic: `pushkey_projectfs` (safe project-file writes), `pushkey_connect` (registry, commit cycle, connect/sync/status/preview/suggest) and `pushkey_connect_migrate` (one-time move of the desktop's project store). Every entry point becomes a thin adapter over them.

**Tech Stack:** Python 3.12, FastAPI (local API), FastMCP, argparse CLI, customtkinter desktop, Next.js 16 static web app (bundled into `pushkey_web/out`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-add-and-connect-design.md` (approved 2026-11-21, owner decisions Q1-Q5 = the recommended answers). Real code shapes this plan was written from: the three mapping reports (storage, entry points, UI) summarised in each task's "Real shapes" lines; line numbers are this branch at `0aed231`.

## Global Constraints

- Branch `feat/add-and-connect` (PR #24 + PR #25 merged in). Baseline: `777 passed, 10 skipped`.
- Commit identity `pushkeydev <pushkeydev@gmail.com>`; no AI attribution lines in commits or PR bodies (AGENTS.md).
- Commit gate: `python C:/Users/aware/.claude/scripts/verified.py run -- python -m pytest <the task's tests> -q` must exit 0 on the same tree within 30 min before a code commit. Commit with named paths only: `git commit -m msg -- path...`.
- New test before its code; record RED with `python C:/Users/aware/.claude/scripts/mutate.py red --cmd "python -m pytest <tests> -q" --record <scratch file>`; report "red seen: yes/no" per test group.
- Never call `monkeypatch.undo()` in a test; use `with monkeypatch.context() as m:`. Project folders in tests are always a subfolder (`tmp_path / "proj"`), never `tmp_path` itself (it is the vault dir).
- Test project folders sit inside the Pushkey git repo (`.pytest_tmp` is repo-local and git-ignored). Any test that needs git behaviour runs `git init` in its project folder first.
- Values never appear in results, logs (`log_event`), the health sidecar, audit text or MCP replies. Audit lines carry key names, project names and relative file paths only.
- Confirmation line format, exact: `Save to {project_name} -> {environment} -> {file} as {var}` (ASCII arrows; spec G3).
- Allowed env file names: basename `.env` or starting with `.env.`; never `.env.example`, `.env.sample`, `.env.template` (spec 5.4, Q3).
- Browser-bundled prefixes (spec 5.5): `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_`, `REACT_APP_`, `EXPO_PUBLIC_`, `NUXT_PUBLIC_`.
- Project record shape (spec 5.1): `{name, created (%Y-%m-%d), default_file (".env"), environment ("dev")}` plus any extra fields carried from the desktop (`ci_*`, `github_*`, `vercel_*`, `railway_*`).
- Connection shape (spec 5.1): `{project, file, var, added}` plus optional `last_error` (str, set when the last write failed, cleared on success).
- Q4: only a master-password session may register or remove a project, in every entry point. Connect, assign and inject require a registered project.
- Q5: `pushkey_tiers.within_limit("max_projects", len(registered))` gates new registrations in every entry point; migration never removes projects. Free tier limit is 1, so existing tests that register 2+ projects patch `pushkey_tiers.current_tier` to `"pro"` with `monkeypatch.setattr`.
- New modules are registered in `pyproject.toml` `py-modules`, `build_exe.py` `SUBMODULES` and `Pushkey.spec` hiddenimports (`tests/test_package_metadata.py` checks the first two).

## Spec rules this plan restates (compare before Task 1)

| Spec | Plan | Verdict |
|---|---|---|
| 5.3 "owns the reload-change-save cycle under the vault lock" | `commit()`: fresh `load_vault*`, mutate, `save_vault*` (its own lock runs the revision check), on `VaultConflictError` reload and retry once, then fail `vault_changed`. | Changed, same guarantee (no lost update). Holding `_vault_write_guard` around `save_vault` deadlocks for 5 s (probed: `VaultBusyError`). |
| 5.4 "in a git repo, ask git (`git check-ignore -q`); if not ignored, append its exact relative path to the root `.gitignore`" | Always make the project's own `.gitignore` list the file (exact relative path) unless an existing line already covers it; git is used only to refuse tracked files. | Changed, stricter. `check-ignore` answers from the enclosing repo, which may not be the project's (test projects sit inside the Pushkey repo). |
| 5.2 step 1 "turn every assignment into an explicit connection" | Only assignments whose key env passes the old desktop filter (`target_env == "all"` or key env `"all"` or equal) become connections; the others are listed in the notice as "not connected: environment differs". | Narrowed: keeps today's behaviour (those keys were never written). |
| 5.6 CLI "value asked with getpass when left out, as today" | `add NAME [VALUE]`: VALUE becomes optional, getpass when omitted (today it is required, `pushkey_cli.py:664`). | Same intent; fixes the MCP warning text that already tells users to run `pushkey add NAME`. |
| 5.1 project record `{name, created, default_file, environment}` | Same, plus the desktop's CI fields carried unchanged. | Widened, no data loss. |

## Safety clauses and the negative test that enforces each

| Clause (spec) | Test (task) |
|---|---|
| A key lands only in a project the user confirmed (anti-goal 1, Q4) | `test_mcp_connect_key_refuses_unregistered_folder` (T9), `test_token_session_cannot_register_project` (T8), `test_cli_token_cannot_add_project` and `test_shell_read_token_cannot_add_key` (T10) |
| Never write outside the project folder (anti-goal 3) | `test_relpath_rejects_parent_segments`, `test_write_refuses_junction_subfolder` (T2), `test_connect_refuses_escape_path` (T6) |
| Never write a secret file git does not ignore (anti-goal 4) | `test_write_adds_exact_path_to_project_gitignore`, `test_tracked_file_is_refused` (T2), `test_existing_backup_files_get_ignored` (T1) |
| Values never in logs, health, audit or MCP replies (anti-goal 5) | `test_connect_result_and_log_have_no_value` (T6), `test_mcp_connect_reply_has_no_value` (T9) |
| Long-lived values never cross the LLM channel (anti-goal 2) | `test_connect_key_takes_no_value_parameter` (T9) |

## Review Focus

1. **Unreadable `config.json`** (salt changed, file corrupt): `load_config()` returns `{"projects": {}}` today, so a registry write or migration would overwrite the real file. Expected: refuse with `config_unreadable` and change nothing. Test `test_registry_refuses_unreadable_config` (T4), `test_migration_refuses_unreadable_config` (T7).
2. **Two apps open at once** (desktop open while the CLI or an agent connects): the desktop's in-memory vault goes stale. Expected: no lost update; the desktop reloads instead of crashing. Tests `test_commit_retries_once_after_conflict` (T5), `test_desktop_save_reloads_after_conflict` (T11).
3. **Paths people actually type**: spaces in folder names in the CLI shell, Windows backslashes in `apps\web\.env.local`, `~`. Expected: accepted and normalised. Tests `test_relpath_normalises_backslashes` (T2), `test_shell_project_add_path_with_spaces` (T10).
4. **Messy env files**: CRLF line endings, a UTF-8 BOM, `export FOO=` lines, the same variable twice. Expected: line endings and BOM kept, `export` kept, every line of the managed variable replaced, nothing else touched. Test `test_apply_assignments_keeps_crlf_bom_export_and_dupes` (T3).
5. **Things disappear**: the project folder is deleted or renamed, a connected key is deleted, a project is unregistered. Expected: status `folder_missing`, no write, no crash; deleting a project removes its connections from every key. Tests `test_status_folder_missing` (T6), `test_unregister_removes_connections` (T5).

---

### Task 1: Backups leave the project folder (spec section 6 step 0)

**Files:**
- Modify: `pushkey_shared.py:9-25` (add `ENV_BACKUPS_DIR = VAULT_DIR / "env-backups"`)
- Modify: `pushkey_env.py:66-127` (`mutate_env_file` backup branch at :110-112; `ensure_gitignore_env` :47-63)
- Test: `tests/test_env_backups.py` (new)

Real shapes: `mutate_env_file(project_dir, vault_entries, *, key_names=None, update_existing, write=True, backup_existing=False, atomic_write=None)`; today `backup_existing` copies `.env` to `<project>/.env.pushkey_backup_<YYYYmmdd_HHMMSS>` on every call, never pruned; callers with `backup_existing=True`: `pushkey.py:1139`, `pushkey_cli.py:568`. conftest redirects any new `pushkey_shared` Path constant under VAULT_DIR automatically.

**Interfaces:**
- Produces: `pushkey_env.backup_env_file(project: Path, relpath: str, data: bytes) -> Path` (writes `ENV_BACKUPS_DIR/<project_id>/<relpath with "/" -> "__">.<YYYYmmdd_HHMMSS_ffffff>.bak`, dir 0o700, file 0o600, keeps the newest 3 per file); `pushkey_env.project_id(project: Path) -> str` = first 16 hex chars of sha256 of `str(project.resolve())`; `LEGACY_BACKUP_GLOB = ".env.pushkey_backup_*"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_env_backups.py`:
  - `test_backup_goes_to_vault_dir_not_project`: project with `.env` `A=1`; `mutate_env_file(project, {"A": {"value": "2"}}, update_existing=True, backup_existing=True)`; assert no file matching `.env.pushkey_backup_*` in `project`, and exactly one `*.bak` under `pushkey_shared.ENV_BACKUPS_DIR / project_id(project)` whose bytes == `b"A=1\n"`.
  - `test_backup_keeps_newest_three`: four calls with values 2..5; assert 3 `.bak` files remain and the oldest kept holds `A=2`... i.e. contents are `A=2`,`A=3`,`A=4` (backups of the file before each of calls 2-4).
  - `test_existing_backup_files_get_ignored`: project with a stray `.env.pushkey_backup_20250101_000000` file and `.gitignore` `.env\n`; one `mutate_env_file(..., write=True)`; assert `.gitignore` lines contain `.env.pushkey_backup_*`; the stray file is not deleted.
- [ ] **Step 2: Run** `python -m pytest tests/test_env_backups.py -q` — expected FAIL (backup in project; no pattern line). Record RED with mutate.py.
- [ ] **Step 3: Implement** `ENV_BACKUPS_DIR`, `project_id`, `backup_env_file`; make `mutate_env_file`'s backup branch call `backup_env_file(project, ".env", env_path.read_bytes())`; make `ensure_gitignore_env` also append `.env.pushkey_backup_*` when any file matching it exists in the project and no line equals it.
- [ ] **Step 4: Run** `python -m pytest tests/test_env_backups.py tests/test_env_injection.py tests/test_cli.py -q` — PASS.
- [ ] **Step 5: Commit** `fix: keep .env backups out of project folders` (`pushkey_shared.py pushkey_env.py tests/test_env_backups.py`).

### Task 2: `pushkey_projectfs` — safe project paths and writes

**Files:**
- Create: `pushkey_projectfs.py`
- Modify: `pushkey_local_api.py:290-366` (`_canonical_project_path`, `_is_link_or_reparse`, `_project_identity`, `_assert_project_target`, `_atomic_project_write` become thin shims mapping `ProjectPathError` to `HTTPException(err.status, err.reason)`; keep the names, tests monkeypatch `fresh_app._atomic_project_write`)
- Modify: `pyproject.toml:52`, `build_exe.py:10-23`, `Pushkey.spec:6`
- Test: `tests/test_projectfs.py` (new)

Real shapes: `_assert_project_target` refuses any target whose parent is not the project root (subfolders fail today) and checks links only on root and leaf; `_atomic_project_write` uses `mkstemp(prefix=f".{filename}.pushkey-", dir=project)`; errors 400 "invalid project path", 400 "project path must be absolute", 400 "project directory not found", 400 "refusing link or reparse-point project target", 400 "project target escapes registered directory", 409 "project path changed during write", 409 "project directory identity changed during write", 409 "temporary project target changed". Keep these reason strings.

**Interfaces:**
- Produces:
  - `class ProjectPathError(ValueError)`: `ProjectPathError(status: int, reason: str)`, attributes `.status`, `.reason`, `str(err) == reason`.
  - `canonical_project_path(raw: str, *, must_exist: bool = True) -> str` (same rules as today; also `expanduser`).
  - `is_link_or_reparse(path: Path) -> bool`; `project_identity(project: Path) -> tuple[int, int]`.
  - `validate_env_relpath(relpath: str) -> str` returns the normalised POSIX relative path; reasons: `"env file path must be relative"`, `"env file path may not contain '..'"`, `"env file name must be .env or start with .env."`, `"env template files are read-only"`, `"invalid env file path"` (empty segment, control char, `:`).
  - `resolve_project_target(registered: str, relpath: str, expected_identity: tuple[int, int]) -> Path`: every existing segment below the project is a real directory (not link/reparse), the leaf is not a link/reparse point, the folder identity still matches; missing subfolders are an error `"env file folder does not exist"` (no folder creation).
  - `atomic_project_write(registered: str, relpath: str, data: bytes, expected_identity: tuple[int, int] | None = None) -> None` (temp file in the target's own folder, prefix `.pushkey-`, the existing checks before and after `os.replace`).
  - `ensure_project_gitignore(registered: str, relpath: str, expected_identity) -> bool` (True when it appended): a line covers the file when, stripped and without a leading `/`, it equals `relpath`, or it has no `/` and `fnmatch(basename, line)`; else append `relpath` to `<project>/.gitignore` via `atomic_project_write`; keeps the file's existing line endings.
  - `is_git_tracked(project: str, relpath: str) -> bool`: runs `git -C <project> ls-files --error-unmatch -- <relpath>` through module-level `_run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess` (timeout 5 s, list argv, no shell); git missing, timeout or non-zero exit → False.

- [ ] **Step 1: Write the failing tests** in `tests/test_projectfs.py`:
  - `test_relpath_normalises_backslashes`: `validate_env_relpath("apps\\web\\.env.local") == "apps/web/.env.local"`.
  - `test_relpath_rejects_parent_segments`: `"../x/.env"`, `"apps/../../.env"` raise `ProjectPathError` with reason `"env file path may not contain '..'"`; `"/abs/.env"` and `"C:/x/.env"` raise `"env file path must be relative"`.
  - `test_relpath_rejects_other_names_and_templates`: `"config.js"` → `"env file name must be .env or start with .env."`; `".env.example"` → `"env template files are read-only"`.
  - `test_write_into_subfolder`: project with `apps/web/`; `atomic_project_write(str(project), "apps/web/.env.local", b"A=1\n")`; file content equals; no `.pushkey-*` temp left.
  - `test_write_refuses_junction_subfolder`: `apps` is a directory link (copy `_link_directory` from `tests/test_health_sidecar.py:326`) to a folder outside the project; write raises reason `"refusing link or reparse-point project target"`; the outside folder has no `.env.local`.
  - `test_write_refuses_missing_subfolder`: reason `"env file folder does not exist"`.
  - `test_write_adds_exact_path_to_project_gitignore`: no `.gitignore`; `ensure_project_gitignore(..., "apps/web/.env.local", ...)` → True and `.gitignore` has the line `apps/web/.env.local`; second call → False; a `.gitignore` containing `.env*` → False and unchanged.
  - `test_tracked_file_is_refused`: `git init`, write `.env.local`, `git add .env.local`, `git -c user.name=t -c user.email=t@t commit -m x`; `is_git_tracked(project, ".env.local") is True`; untracked `.env` → False; `_run_git` patched to raise `FileNotFoundError` → False.
- [ ] **Step 2: Run** `python -m pytest tests/test_projectfs.py -q` — FAIL (module missing is a collection error, not RED: first create an empty `pushkey_projectfs.py` with `class ProjectPathError(ValueError): pass` and stub functions raising `NotImplementedError`, then record RED).
- [ ] **Step 3: Implement** the module; move the bodies from `pushkey_local_api.py:290-366`, generalise to relative paths; make the local API functions shims; register the module in the three packaging files.
- [ ] **Step 4: Run** `python -m pytest tests/test_projectfs.py tests/test_local_api.py tests/test_package_metadata.py tests/test_packaging.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: add pushkey_projectfs for safe project-file writes`.

### Task 3: Env text helpers (pure functions)

**Files:**
- Modify: `pushkey_env.py`
- Test: `tests/test_env_text.py` (new)

Real shapes: `_ENV_LINE = ^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$` misses `export` and indented lines; `format_env_value` quotes with `"` and escapes `\\ \r \n "` only when needed; `sanitize_env_value` strips CR/LF. Desktop's richer parser (`pushkey.py:933-1000`) lives in the GUI module and upper-cases names; do not import it.

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class EnvLine: index: int; name: str; value_text: str; export: bool`
  - `parse_env_lines(text: str) -> list[EnvLine]` (regex `^\s*(export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$`, names in original case, a leading BOM ignored for matching).
  - `decode_env_value(value_text: str) -> str` (double-quoted: inverse of `format_env_value`; single-quoted: literal; else the text as is).
  - `render_connected_value(value: object) -> str` = `format_env_value(sanitize_env_value(value))` — the one transform used to write and to compare.
  - `apply_env_assignments(text: str, assignments: dict[str, str]) -> tuple[str, list[str], list[str]]` returns `(new_text, added_vars, updated_vars)`; replaces every line of an assigned var (keeps its indentation and `export `), appends missing vars after a single `# Managed by Pushkey` header (header added only when absent), keeps BOM and the file's line ending (`\r\n` if the text contains it), always ends with a newline; values are passed already rendered.

- [ ] **Step 1: Failing tests** in `tests/test_env_text.py`:
  - `test_parse_keeps_case_and_export`: `"export NEXT_PUBLIC_X=1\n  B = 2\n# c\n"` → names `["NEXT_PUBLIC_X", "B"]`, first `export is True`.
  - `test_decode_round_trips_format`: for `v in ["plain", "with space", 'q"uote', "a#b", ""]`: `decode_env_value(format_env_value(v)) == v`; `decode_env_value("'lit $x'") == "lit $x"`.
  - `test_apply_assignments_keeps_crlf_bom_export_and_dupes`: input `"\ufeffexport A=1\r\nB=2\r\nA=old\r\n"`, assignments `{"A": "9", "C": "3"}` → output `"\ufeffexport A=9\r\nB=2\r\nA=9\r\n\r\n# Managed by Pushkey\r\nC=3\r\n"`, added `["C"]`, updated `["A"]`.
  - `test_apply_assignments_header_once`: applying `{"D": "4"}` to a text that already has the header appends `D=4` without a second header line.
- [ ] **Step 2: Run** `python -m pytest tests/test_env_text.py -q` — FAIL (record RED after adding stubs).
- [ ] **Step 3: Implement** the five names in `pushkey_env.py`.
- [ ] **Step 4: Run** `python -m pytest tests/test_env_text.py tests/test_env_injection.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: env text helpers for connected variables`.

### Task 4: Config that cannot be silently wiped

**Files:**
- Modify: `pushkey_vault.py:541-573`
- Test: `tests/test_config_storage.py` (extend)

Real shapes: `load_config()` returns `{"projects": {}}` for a missing OR undecryptable file; `save_config` writes a fixed `config.tmp` then `os.replace`; no lock. Lock helper to reuse: `pushkey_locking.bounded_file_lock(path, *, timeout_seconds=5.0)` raising `FileLockTimeout`.

**Interfaces:**
- Produces: `class ConfigUnreadableError(RuntimeError)`; `load_config(*, strict: bool = False)` (strict: an existing file that neither decrypts nor parses as legacy JSON, or decrypts to a non-dict, raises `ConfigUnreadableError("config_unreadable")`; non-strict unchanged); `config_lock()` context manager = `bounded_file_lock(VAULT_DIR / ".config.lock")`, timeout → `ConfigUnreadableError("config_busy")`; `update_config(mutate: Callable[[dict], T]) -> T` = under `config_lock()`: `load_config(strict=True)`, `mutate(cfg)`, `save_config(cfg)` (temp name made unique per process: `config.<pid>.tmp`).

- [ ] **Step 1: Failing tests**: `test_strict_load_raises_on_garbage` (write 40 random bytes to `CONFIG_FILE`; `load_config(strict=True)` raises `ConfigUnreadableError`; `load_config()` still returns `{"projects": {}}`); `test_update_config_keeps_other_settings` (seed `{"projects": {}, "theme": "light"}`; `update_config(lambda c: c["projects"].__setitem__("/p", {"name": "p"}))`; reload has both `theme` and `/p`); `test_registry_refuses_unreadable_config` (garbage file; `update_config(...)` raises and the file bytes are unchanged).
- [ ] **Step 2: Run** `python -m pytest tests/test_config_storage.py -q` — FAIL; record RED.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m pytest tests/test_config_storage.py tests/test_multi_project.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: strict config loading and update_config`.

### Task 5: `pushkey_connect` core — commit cycle, key replacement, project registry

**Files:**
- Create: `pushkey_connect.py`
- Modify: packaging files (as Task 2)
- Test: `tests/test_connect_core.py` (new)

Real shapes: `load_vault(password) -> (VaultData, vault_key)`; `load_vault_with_key(vault_key) -> (VaultData, vault_key)` or `(None, None)`; `save_vault(vault, password, *, vault_key=...)` (V3 needs `vault_key`), `save_vault_with_key(vault, vault_key)`; both raise `VaultConflictError("stale_vault_revision")` when the file changed since load and update `vault._pushkey_revision` on success; `publish_saved_vault(vault)` must run after save, outside any guard, raises `HealthSidecarError`/`VaultBusyError`; `log_event(message)` never raises. Rotation today differs per entry point (entry-points report E.4).

**Interfaces:**
- Produces:
  - `class ConnectError(RuntimeError)` with `.code: str` and `.detail: dict` (codes used below and in Task 6).
  - `@dataclass class CommitResult: value: Any; vault: VaultData; health_warning: Optional[str]`
  - `commit(mutate: Callable[[VaultData], T], *, vault_key: Optional[bytes], password: Optional[str], target: Optional[dict] = None) -> CommitResult`: reload (`load_vault_with_key` when `vault_key`, else `load_vault(password)`; `None` → `ConnectError("vault_unavailable")`), `mutate(fresh)`, save (`save_vault(fresh, password, vault_key=vault_key)` when `password`, else `save_vault_with_key`), one retry on `VaultConflictError` (reload, mutate again), second conflict → `ConnectError("vault_changed")`; then `publish_saved_vault` (warning `"health_publication_failed"` on `HealthSidecarError`/`VaultBusyError`); if `target` is given, `adopt_vault(target, fresh)`.
  - `adopt_vault(target: dict, fresh: VaultData) -> None` (clear+update contents and copy `_pushkey_revision`).
  - `replace_value(entry: dict, new_value: str, *, now: Optional[str] = None) -> None`: history insert `{"value": old, "retired": now}` (max 10), `previous`, `value`, `rotated = now` (`%Y-%m-%dT%H:%M:%S`), `rotation_count += 1`; never touches `projects`, `connections`, `next_value`, `env`, `provider`, `notes`.
  - Registry (config side, through `update_config`): `registered_projects(config: dict) -> dict[str, dict]` (only absolute-path keys); `register_project(path: str, *, name: Optional[str] = None) -> tuple[str, dict]` (canonical path, record per Global Constraints, `ConnectError("project_exists")`, `ConnectError("project_limit")` via `within_limit("max_projects", len(registered))`, `ProjectPathError` passes through); `unregister_project(path: str, *, vault_key, password, target=None) -> CommitResult` (commit: drop the path from every key's `projects` and its connections; then `update_config` removes the record).

- [ ] **Step 1: Failing tests** in `tests/test_connect_core.py` (seed with `save_vault({...}, "pw")` then `load_vault("pw")`):
  - `test_commit_saves_and_adopts`: mutate adds `notes="x"` to key `A`; `target` dict gets the change and `target._pushkey_revision == load_vault("pw")[0]._pushkey_revision`.
  - `test_commit_retries_once_after_conflict`: mutate saves an unrelated change through a separately loaded copy on its first call only; result vault holds both changes; mutate called twice.
  - `test_commit_gives_up_after_second_conflict`: mutate always causes an external save → `ConnectError` with code `"vault_changed"`.
  - `test_replace_value_keeps_connections`: entry with `projects`, `connections`, `next_value`; after `replace_value(entry, "new")` those three are unchanged, `history[0]["value"]` is the old value, `rotation_count == 1`.
  - `test_register_project_and_limit`: free tier (default): first `register_project(str(p1))` ok, second raises `project_limit`; with `monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")` it succeeds; duplicate → `project_exists`; record equals `{"name": "p1", "created": <today>, "default_file": ".env", "environment": "dev"}`.
  - `test_unregister_removes_connections`: two keys connected to p1 and one to p2; `unregister_project(p1)` leaves only p2 connections/allowlist and removes the p1 config record.
- [ ] **Step 2: Run** `python -m pytest tests/test_connect_core.py -q` — FAIL; record RED.
- [ ] **Step 3: Implement**; register the module.
- [ ] **Step 4: Run** `python -m pytest tests/test_connect_core.py tests/test_package_metadata.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: pushkey_connect commit cycle, key replacement and project registry`.

### Task 6: `pushkey_connect` — preview, connect, sync, status, disconnect, suggest

**Files:**
- Modify: `pushkey_connect.py`
- Test: `tests/test_connect_flow.py` (new)

**Interfaces:**
- Consumes: Task 2 (`validate_env_relpath`, `resolve_project_target`, `atomic_project_write`, `ensure_project_gitignore`, `is_git_tracked`, `project_identity`, `ProjectPathError`), Task 3 (`parse_env_lines`, `decode_env_value`, `render_connected_value`, `apply_env_assignments`), Task 1 (`backup_env_file`), Task 5 (`commit`, `registered_projects`, `ConnectError`).
- Produces:
  - `@dataclass class Preview: key: str; project: str; project_name: str; file: str; var: str; environment: str; line: str; change: Literal["add", "replace", "none"]; gitignore_change: bool; needs_confirm: list[str]; conflict_key: Optional[str]`
  - `preview(vault, config, *, key_name, project, file=None, var=None) -> Preview`. Defaults: `file = record["default_file"]`, `var = key_name`. Errors (`ConnectError` codes): `key_not_found`, `project_not_registered`, `var_taken` (another key already has `(project, file, var)`; `detail={"key": other}`), `file_tracked_by_git`, `invalid_var` (var must match `^[A-Za-z_][A-Za-z0-9_]*$`); path errors pass through as `ProjectPathError`. `needs_confirm` codes: `"env_mismatch"` (key `env` not in `{record["environment"], "all"}`), `"public_prefix"` (var starts with a browser prefix and neither the key name nor the var contains `ANON`, `PUBLISHABLE`, `PUBLIC_KEY`, `_URL`, `CLIENT_ID`, and the value does not start with `pk_` or `sb_publishable_`).
  - `@dataclass class ConnectResult: key: str; project: str; file: str; var: str; written: bool; reason: Optional[str]; change: str; gitignore_changed: bool; health_warning: Optional[str]`
  - `connect(*, key_name, project, file=None, var=None, value=None, provider=None, env=None, notes="", write=True, confirmed: Iterable[str] = (), replace_source: bool = False, vault_key, password, target=None, actor: str) -> ConnectResult`: order per spec 5.3 (add or `replace_value` when `value` given; allowlist + connection; commit; write file with backup + gitignore; `log_event(f"{actor}: connected {key} -> {project_name} {file} as {var}")`). Missing confirmations → `ConnectError("confirmation_required", detail={"needs": [...]})` before any write. A file failure keeps the connection, sets `last_error`, returns `written=False, reason=<reason>`.
  - `sync(*, key_name=None, project=None, vault_key, password, target=None, actor: str) -> list[ConnectResult]`: rewrite every matching connection (Q2: replace values); folders not on this computer → `written=False, reason="folder_missing"`; clears or sets `last_error`.
  - `@dataclass class ConnectionStatus: key: str; project: str; project_name: str; file: str; var: str; state: Literal["up_to_date", "out_of_date", "not_in_file", "file_missing", "folder_missing", "not_ignored", "not_written"]; reason: Optional[str]`
  - `status(vault, config, *, key_name=None, project=None) -> list[ConnectionStatus]` (compares `decode_env_value(line.value_text)` with `sanitize_env_value(value)`; `last_error` set and not up to date → `not_written`; values never in the result).
  - `disconnect(*, key_name, project, file, var, remove_line=False, vault_key, password, target=None, actor) -> CommitResult` (allowlist entry removed when it was the key's last connection to that project).
  - `@dataclass class Suggestion: projects: list[tuple[str, str]]; files: list[tuple[str, str]]; vars: list[tuple[str, str]]` (each `(value, reason)`).
  - `suggest(vault, config, *, key_name, value=None, cwd=None, project=None) -> Suggestion`: projects (cwd registered → `"current folder"`; `config["last_project"]` → `"last used"`; projects connected to keys of the same provider → `"used with other <Provider> keys"`); files for the chosen project (`default_file` → `"project default"` when set by the user; else `.env.local` when `next.config.*` or `vite.config.*` exists → `"Next.js or Vite project"`, else `.env`); vars (names from `.env.example`, `.env.sample`, the target file whose lower-case form contains one of `PROVIDERS[provider]["patterns"]` and are not connected yet → `"found in <file>"`; then the key name → `"same as the key name"`). Reads names only, never values.

- [ ] **Step 1: Failing tests** in `tests/test_connect_flow.py` (fixture: pro tier, project `tmp_path/"acme-web"` registered, key `SUPABASE_ANON_KEY` value `sb_publishable_x` env `dev`):
  - `test_preview_line_and_defaults`: `preview(...).line == "Save to acme-web -> dev -> .env as SUPABASE_ANON_KEY"`, `change == "add"`, `gitignore_change is True`.
  - `test_connect_writes_and_records`: `connect(..., file=".env.local", var="NEXT_PUBLIC_SUPABASE_ANON_KEY", actor="test")` → file has `NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_x`, `.gitignore` has `.env.local`, vault entry `connections == [{"project": p, "file": ".env.local", "var": "NEXT_PUBLIC_SUPABASE_ANON_KEY", "added": ANY}]` and `p in projects`.
  - `test_connect_refuses_unregistered_folder`: unregistered folder → `project_not_registered`, nothing written.
  - `test_connect_refuses_escape_path`: `file="../.env"` → `ProjectPathError`; no file outside the project.
  - `test_public_prefix_needs_confirmation`: key `SUPABASE_SERVICE_ROLE_KEY` value `eyJ...` to var `NEXT_PUBLIC_SR` → `confirmation_required` with `needs == ["public_prefix"]`; with `confirmed={"public_prefix"}` it writes.
  - `test_env_mismatch_needs_confirmation`: key env `prod`, project env `dev` → `needs == ["env_mismatch"]`.
  - `test_var_taken_by_other_key`: second key to the same `(project, file, var)` → `var_taken` with `detail["key"]`.
  - `test_sync_replaces_after_rotation`: connect, then `commit(lambda v: replace_value(v["SUPABASE_ANON_KEY"], "sb_publishable_y"))`, `sync(key_name=...)` → file value `sb_publishable_y`, a `.bak` exists under `ENV_BACKUPS_DIR`.
  - `test_status_states`: up_to_date after connect; edit the file by hand → `out_of_date`; delete the line → `not_in_file`; delete file → `file_missing`; rename folder → `folder_missing`; remove the `.gitignore` line → `not_ignored`.
  - `test_status_folder_missing`: unregister nothing, delete folder; `sync` returns `written=False, reason="folder_missing"` and does not raise.
  - `test_failed_write_is_not_written`: patch `pushkey_projectfs.atomic_project_write` to raise `ProjectPathError(409, "project directory identity changed during write")` → `written is False`, connection kept, `status(...)[0].state == "not_written"` with that reason; next successful `sync` clears it.
  - `test_connect_result_and_log_have_no_value`: capture `log_event` messages with `monkeypatch.setattr(pushkey_connect, "log_event", ...)`; `"sb_publishable_x"` not in any message nor in `repr(result)`.
  - `test_suggest_from_env_example`: project with `next.config.js` and `.env.example` containing `NEXT_PUBLIC_SUPABASE_ANON_KEY=` and `OPENAI_API_KEY=`; `suggest(...)` → `files[0] == (".env.local", "Next.js or Vite project")`, `vars[0] == ("NEXT_PUBLIC_SUPABASE_ANON_KEY", "found in .env.example")`, `OPENAI_API_KEY` not suggested.
- [ ] **Step 2: Run** `python -m pytest tests/test_connect_flow.py -q` — FAIL; record RED.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m pytest tests/test_connect_flow.py tests/test_connect_core.py tests/test_projectfs.py tests/test_env_text.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: connect, sync, status and suggestions`.

### Task 7: One-time migration (`pushkey_connect_migrate`)

**Files:**
- Create: `pushkey_connect_migrate.py`; packaging files.
- Test: `tests/test_connect_migrate.py` (new)

Real shapes: desktop entries `config["projects"][NAME] = {path, keys, added (isoformat), target_env, ci_platform?, github_owner?, ...}` (`pushkey.py:7868-7873`, `8083-8084`); CLI/web entries `config["projects"][ABS_PATH] = {name, created}`; allowlist `vault[KEY]["projects"]: list[str]`; desktop env rule `_env_match`: `target_env == "all" or key_env == "all" or key_env == target_env` (`pushkey.py:1130-1136`); desktop `delete_key` leaves stale names in `keys`.

**Interfaces:**
- Produces:
  - `@dataclass class MigrationReport: moved: list[str]; connections_added: int; every_key_projects: list[str]; env_skipped: list[tuple[str, str]]; missing_keys: list[tuple[str, str]]`
  - `plan_migration(vault: dict, config: dict) -> MigrationReport` mutates both dicts in memory (pure apart from that): name-keyed entries with a usable `path` → path-keyed record (`name`, `created` from `added[:10]` or today, `default_file ".env"`, `environment = target_env if in ENV_LEVELS else "dev"`, extra fields kept); every listed key that exists and passes the env rule → allowlist + connection `{file ".env", var KEY}`; others into `env_skipped` / `missing_keys`; empty `keys` → `every_key_projects` (Q1: no keys); old entries moved to `config["projects_legacy"]`; every existing allowlist entry (any origin) without a connection gets one; `config["connect_schema"] = 1`; `config["connect_notice"] = {"every_key_projects": [...], "env_skipped": [...]}` when either is non-empty. Running it again on its own output adds nothing.
  - `ensure_migrated(*, vault_key, password, target=None) -> Optional[MigrationReport]`: under `config_lock()`, `load_config(strict=True)` (raises `ConfigUnreadableError`); returns `None` when `connect_schema == 1` and no name-keyed entries remain; else `commit()` the vault side first, then save the config side.
  - `dismiss_notice() -> None` (removes `connect_notice` via `update_config`).

- [ ] **Step 1: Failing tests**:
  - `test_migrates_desktop_entry`: config `{"projects": {"acme": {"path": str(p), "keys": ["A", "GONE"], "added": "2026-01-02T03:04:05", "target_env": "all", "ci_platform": "github"}}}`, vault `A` → record at canonical `p` with `name "acme"`, `created "2026-01-02"`, `ci_platform` kept; `A` connected `{file ".env", var "A"}`; `missing_keys == [("acme", "GONE")]`; `"acme"` under `projects_legacy`.
  - `test_empty_list_gets_no_keys_and_notice`: `keys: []` → no allowlist entries, `connect_notice["every_key_projects"] == [p]`.
  - `test_env_filter_respected`: `target_env "dev"`, key env `prod` → not connected, listed in `env_skipped`.
  - `test_existing_assignment_becomes_connection`: CLI-style record + `vault["B"]["projects"] = [p]` → one connection for `B`.
  - `test_migration_is_idempotent`: `plan_migration` twice → second report all empty, dicts equal.
  - `test_migration_refuses_unreadable_config`: garbage `config.json` → `ensure_migrated` raises `ConfigUnreadableError`, file bytes and vault unchanged.
- [ ] **Step 2: Run** — FAIL; record RED.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m pytest tests/test_connect_migrate.py tests/test_connect_core.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: one-time migration to the shared project store`.

### Task 8: Local web API

**Files:**
- Modify: `pushkey_local_api.py` (routes LA:776-1020, models LA:85-148, unlock LA:601-639)
- Modify: `docs/local-api-v1.md` (rows for every new route; contract tests read them)
- Test: `tests/test_local_api_connect.py` (new); update `tests/test_local_api.py` where behaviour changes on purpose (list them in the report).

Real shapes: `require_scope(scope)` takes one scope and lets agent tokens through on scope alone; `require_writable` = password session only (LA:694-697); models are `StrictBody` (extra fields rejected); `_save(sess, response)` sets `X-Pushkey-Warning`; inject today skips existing values and allows explicit `keys` outside the allowlist (LA:977-984).

Changes (each with its test):
- Unlock (password, recovery and agent token) calls `ensure_migrated(..., target=sess.vault)`; `ConfigUnreadableError` → 500 `{"detail": "config_unreadable"}` and the session stays locked.
- `POST /api/projects` and `DELETE /api/projects` → `Depends(require_writable)`; use `register_project` / `unregister_project`; `project_limit` → 402 `{"detail": "project_limit"}`; `project_exists` → 409.
- `POST /api/keys`: `KeyCreate` gains `connect: Optional[ConnectBody]` (`project: str`, `file: Optional[str]`, `var: Optional[str]`, `confirmed: list[Literal["env_mismatch","public_prefix"]] = []`); `overwrite=true` uses `replace_value` (keeps connections) then `sync`; with `connect`, calls `connect(...)` and returns `{"name","provider","env","connection": <ConnectResult as dict>}`.
- Rotate and promote use `replace_value` + `sync`; responses gain `"synced": [<ConnectResult dicts>]` (no values). An agent-token session without `inject` still rotates; the response carries `"not_synced": [{"project","file","var"}]` instead (spec 5.3).
- New routes: `POST /api/connections/preview` [read] body `{key, project, file?, var?}` → Preview dict; `POST /api/connections` [write and inject] → ConnectResult (write+inject: `Depends(require_scope("write"))` and `Depends(require_scope("inject"))`); `DELETE /api/connections` [write] body `{key, project, file, var}`; `GET /api/connections?key=&project=` [read] → `{"connections": [ConnectionStatus dicts]}`; `POST /api/connections/sync` [inject] body `{key?, project?}`; `GET /api/connections/suggest?key=&project=` [read] → Suggestion; `GET /api/connect/notice` [read] and `DELETE /api/connect/notice` [write].
- `POST /api/projects/assign` → `connect(write=False)` per key (file/var defaults); `/inject` → `sync(project=path)` limited to `body.keys` when given; explicit keys that are not connected → 400 `keys not connected: [...]`.
- `GET /api/projects` returns `keys` from connections plus `"connections": <count>`; `GET /api/keys` rows gain `"connections": <count>`.
- `ConnectError` → status map: `key_not_found` 404, `project_not_registered` 404, `var_taken` 409, `confirmation_required` 409 with `{"detail":"confirmation_required","needs":[...]}`, `file_tracked_by_git` 400, `vault_changed` 409, `vault_unavailable` 423; `ProjectPathError` → its `status` and `reason`.

- [ ] **Step 1: Failing tests** (`tests/test_local_api_connect.py`, reuse `fresh_app`/`client`/`auth`/`token_unlocked` patterns from `tests/test_local_api.py:20-49, 346-354, 1261-1273`): `test_add_key_with_connect_writes_file`, `test_preview_returns_line`, `test_token_session_cannot_register_project` (write+inject token → 403 on `POST /api/projects`), `test_connections_route_needs_write_and_inject` (write-only token → 403), `test_overwrite_keeps_connections_and_syncs`, `test_rotate_syncs_connected_files`, `test_inject_replaces_connected_values` (replaces the old `test_inject_skips_existing_env_keys` expectation on purpose; unconnected existing variables stay untouched), `test_inject_refuses_unconnected_explicit_keys`, `test_project_limit_returns_402`, `test_unlock_runs_migration_and_notice_route`, `test_conflict_maps_to_409`.
- [ ] **Step 2: Run** — FAIL; record RED.
- [ ] **Step 3: Implement**; add the `docs/local-api-v1.md` rows.
- [ ] **Step 4: Run** `python -m pytest tests/test_local_api_connect.py tests/test_local_api.py tests/test_local_contracts.py tests/test_local_api_contract_static.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: add-and-connect routes in the local API`.

### Task 9: MCP server

**Files:**
- Modify: `pushkey_mcp.py` (tools MCP:249-575, `_SESSION` MCP:79, unlock MCP:90-115)
- Modify: `docs/mcp-setup.md`
- Test: `tests/test_mcp_connect.py` (new); adjust `tests/test_mcp.py` tests whose behaviour changes on purpose (assign to an unregistered folder, inject explicit unconnected keys).

Real shapes: `_require_scope(scope)` returns `None` or an error dict; tools return `{"success": bool, ...}`; the three plaintext warnings (MCP:294-299, 423-428, 485-490) keep their text; `assign_key` accepts any path today; `rotate_key`/`rotate_to_backup` keep no history.

Changes:
- Unlock runs `ensure_migrated(target=_SESSION["vault"])`.
- New tools: `preview_connection(name: str, project_path: str, file: str | None = None, var: str | None = None) -> dict` [read]; `connect_key(name: str, project_path: str, file: str | None = None, var: str | None = None, confirm: list[str] | None = None) -> dict` [write and inject; name only]; `key_usage(name: str) -> dict` [read] → `{"name", "connections": [ConnectionStatus dicts]}`.
- `assign_key` → `connect(write=False)`; `inject_env` → `sync(project=...)` (explicit keys must be connected); both refuse unregistered folders with `{"success": False, "error": "project_not_registered", "hint": "A person must add this folder as a project in Pushkey first."}`.
- `add_key(overwrite=True)`, `rotate_key`, `rotate_to_backup` use `replace_value` then `sync` when the session has `inject` (else reply lists `"not_synced": [...]`).
- Every reply built from core results; no value fields.

- [ ] **Step 1: Failing tests**: `test_mcp_connect_key_refuses_unregistered_folder`, `test_mcp_connect_reply_has_no_value` (`json.dumps(reply)` lacks the value), `test_connect_key_takes_no_value_parameter` (`inspect.signature(mcp_mod.connect_key)` has no parameter named `value`), `test_connect_key_needs_write_and_inject` (session scopes `["read","write"]` → `scope_denied` for `inject`), `test_rotate_to_backup_syncs_connected_file`, `test_add_key_warning_text_unchanged` (substrings `"MCP client context"` and `` "pushkey add NEW_KEY" ``).
- [ ] **Step 2: Run** — FAIL; record RED.
- [ ] **Step 3: Implement**; update `docs/mcp-setup.md` tool list.
- [ ] **Step 4: Run** `python -m pytest tests/test_mcp_connect.py tests/test_mcp.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: add-and-connect tools in the MCP server`.

### Task 10: CLI and interactive shell

**Files:**
- Modify: `pushkey_cli.py` (argparse CLI:646-732, `_COMMAND_SCOPES` CLI:339-368, `CLI_COMMANDS` CLI:48-51, shell CLI:168-213, 916-1478, `_render_stale_warnings` CLI:1073-1098, help CLI:1487-1532)
- Test: `tests/test_cli_connect.py` (new); update `tests/test_cli.py:659-668` (the `_run_repl_session` lambda gains `scopes`).

Real shapes: `cmd_*(args, vault, password, vault_key=None)`; `_open_vault(args)` returns `(vault, password|None, vault_key, scopes|None)`; scope gate is fail-open for unmapped commands and absent in the shell (`_unlock_into_repl` drops scopes, CLI:210-213); shell splits with `line.split()`; `_render_stale_warnings` calls `_repl_rotate(vault, password, target)` without `vault_key` (crashes on V3, CLI:1096).

Changes:
- `add NAME [VALUE] [--notes] [--project PATH] [--file F] [--as VAR] [--yes]`: VALUE optional (getpass `Value for NAME (hidden): `); with `--project` prints the preview line and asks `Confirm? [y/N]` unless `--yes`; prints `Saved in the vault` / `Connected and written to <file>` (or the reason).
- New commands: `connect NAME --project PATH [--file F] [--as VAR] [--yes]` (scopes write+inject), `where NAME` (read; one row per connection: project name, file, var, state), `sync [NAME] [--project PATH]` (inject), `project add PATH [--name N]` and `project remove PATH` (master password only; token → EXIT_AUTH).
- `_COMMAND_SCOPES` values become tuples (`("write", "inject")` for connect and add with `--project`); the gate fails closed for any command not in the map.
- Shell: `_run_repl_session(vault, password, vault_key=None, scopes=None)`; every shell command goes through the same gate; token sessions cannot run `project add/remove`; split lines with `shlex.split(line, posix=(os.name != "nt"))`; `project add/assign/inject`, `inject`, `rotate` route through `pushkey_connect`.
- `inject [--project] [--all]`: `sync(project=...)`; `--all` (master password only) connects every key with defaults first.
- `rotate`, shell rotate, stale-warning rotate: `replace_value` + `sync`; pass `vault_key`. A token session without `inject` still rotates and prints `Not updated (token lacks inject): <project> <file>` per connection.
- `_open_vault` runs `ensure_migrated`; prints the one-time notice text when `connect_notice` exists.

- [ ] **Step 1: Failing tests**: `test_add_with_project_connects` (Namespace with `project`, `file=".env.local"`, `as_var="NEXT_PUBLIC_X"`, `yes=True`), `test_add_prompts_for_value_when_omitted` (patch `cli.getpass.getpass`), `test_cli_token_cannot_add_project` (exit code `EXIT_AUTH`), `test_shell_read_token_cannot_add_key` (`_handle_repl_command("add", ...)` with scopes `["read"]` refused, vault unchanged), `test_shell_project_add_path_with_spaces` (folder `tmp_path/"My Project"`), `test_unmapped_command_fails_closed`, `test_where_lists_states`, `test_stale_warning_rotate_saves_v3_vault` (no `VaultFormatError`).
- [ ] **Step 2: Run** — FAIL; record RED.
- [ ] **Step 3: Implement**; update help text and `CLI_COMMANDS`.
- [ ] **Step 4: Run** `python -m pytest tests/test_cli_connect.py tests/test_cli.py tests/test_cli_agent_tokens.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: add-and-connect in the CLI; shell honours token scopes`.

### Task 11: Desktop switches to the shared store (no new screens)

**Files:**
- Modify: `pushkey.py` (login 1900-1974, `AppFrame.__init__` 2166-2174, `save` 2371-2373, project functions 3757-3759, 3924-3927, 4630, 6334-6366, 7134-7136, 7186-7187, 7686-8186, 8651; copy 2015-2027, 7670, 7688)
- Test: `tests/test_desktop_projects.py` (new; FakeApp + `types.MethodType` pattern from `tests/test_ui_helpers.py:122-136`, fake `messagebox`)

Real shapes: see the UI mapping report sections 1.0-1.2 and risks 1-18 (empty list = every key in six places; name-prefix auto-assign in four; `self.vault`/`self.config` loaded once; `save()` writes the whole config; `VaultConflictError` never caught; CI fields on project dicts).

Changes:
- After login: `ensure_migrated(vault_key=..., password=..., target=self.vault)`; show the notice dialog text when `connect_notice` exists.
- `AppFrame.save()`: vault save catches `VaultConflictError` → reload vault from disk, `adopt_vault`, show "The vault changed in another Pushkey window or tool. It has been reloaded; please repeat your last change."; config side uses `update_config` and writes only desktop-owned keys (everything except `projects`, `projects_legacy`, `connect_schema`, `connect_notice`, `last_project`).
- Project list, cards, scans, sync and CI sync read `registered_projects(config)` (path = dict key, title = `name`); add/remove project call `register_project` / `unregister_project` (Q5 gate message reused from `_gate`); assign dialog writes connections through `connect(write=False)`; "Sync .env" → `sync(project=...)` with the existing confirm dialog; `_auto_inject_key(s)` → `sync(key_name=...)` (connections only); remove `_auto_match_keys` callers and the "empty list = every key" branches; `inject_env_file` with an empty list raises `ValueError` instead of writing all keys; `_cli_main inject` requires `--keys`.
- Every core call passes `target=self.vault` and reloads `self.config = load_config()` afterwards.
- Copy changes: help text and empty-state text no longer promise automatic writes into every project.

- [ ] **Step 1: Failing tests**: `test_desktop_login_runs_migration`, `test_desktop_save_reloads_after_conflict` (external save between load and `save()` → no exception, vault reloaded, message shown via fake `messagebox`), `test_desktop_save_keeps_projects_added_elsewhere` (register a project through `register_project` after the desktop loaded config; desktop `save()` keeps it), `test_add_key_no_longer_writes_unassigned_projects` (project with no connections gets no file), `test_project_scan_roots_use_registry_paths`, `test_inject_env_file_refuses_empty_list`.
- [ ] **Step 2: Run** — FAIL; record RED.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m pytest tests/test_desktop_projects.py tests/test_ui_helpers.py tests/test_env_injection.py tests/test_multi_project.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: desktop uses the shared project store`.

### Task 12: Desktop screens (add-key connect section, "Used in", notice)

**Files:**
- Modify: `pushkey.py` (`_show_add_key_modal` 5775-5845, `add_key` 5847-5890, `_render_expand_panel` 5402-5561)
- Test: `tests/test_desktop_projects.py` (extend)

Changes (layout per the mockup artboard 1 and `make_btn`/`field` style at 1315-1337, 5787-5792):
- `add_key` returns `bool`; the window closes only on success (button and `<Return>`).
- Connect section: "Connect to a project" checkbox (on when `suggest()` returns a project), project option menu (registered names + "Add a project folder…"), file option menu (suggested files), variable choices (suggested vars, `CTkSegmentedButton` or radio list), preview line label from `preview()`, extra confirm dialog for `needs_confirm`; button text "Save & connect" / "Save". Window height grows to fit (no fixed 360).
- Expand panel: the PROJECTS pill block becomes "USED IN": one row per `status()` entry (project name, file, var, state pill reusing the health pill style; "Update now" for `out_of_date`/`not_in_file`/`not_written`; "Disconnect").
- Rotation paths (`add_key` rotate branch, `_apply_rotation`, `_promote_backup_key`) use `replace_value` + `sync` and show per-project results.

- [ ] **Step 1: Failing tests** (logic only, no Tk root): `test_add_key_returns_false_on_missing_info`, `test_add_key_with_connection_calls_connect` (fake widgets with `.get()`), `test_used_in_rows_from_status` (pure helper `_used_in_rows(status_list) -> list[tuple]` extracted for testing), `test_promote_backup_syncs`.
- [ ] **Step 2: Run** — FAIL; record RED.
- [ ] **Step 3: Implement**; then launch the desktop app once (`python pushkey.py`) against a scratch HOME and take a screenshot of the add-key window and an expanded key; attach to the report.
- [ ] **Step 4: Run** `python -m pytest tests/test_desktop_projects.py tests/test_ui_helpers.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: desktop add-and-connect screens`.

### Task 13: Web app screens and bundle

**Files:**
- Modify: `web-app/src/lib/api.ts`, `web-app/src/components/vault-tab.tsx`, `web-app/src/components/projects-tab.tsx`, `web-app/src/app/page.tsx` (notice), `web-app/tests/e2e/support/mock-local-api.ts`
- Regenerate: `pushkey_web/out/**`, `pushkey_web/_manifest.py` (only via `npm run build` in `web-app/`)
- Test: Python static tests (`tests/test_local_contracts.py`, `tests/test_local_api_contract_static.py`, `tests/test_web_app_accessibility_static.py`, `tests/test_web_app_states.py`, `tests/test_web_app_security.py`), `npm run lint`, `npm run test:e2e -- accessibility.spec.ts wcag.spec.ts --project=chromium`

Changes (per the mockup artboard 1):
- `api.ts`: named types `Connection`, `ConnectionStatus`, `Preview`, `Suggestion`, `ConnectResult` (no generic args containing `>`); functions `previewConnection`, `connect`, `disconnect`, `listConnections`, `syncConnections`, `suggestConnection`, `getNotice`, `dismissNotice`; `addKey` accepts `connect`.
- Add-key form: "Connect to a project" checkbox, project select, file select, variable choices with reasons, preview box, confirm dialog for `needs`, submit "Save & connect" / "Save".
- Vault table: a fourth inline row "Used in" per key with its own `aria-expanded`/`aria-controls` toggle, rows with state badges, "Update now", "Disconnect".
- Projects tab: card shows connections and "Update all" (sync); existing aria strings unchanged.
- One-time notice banner (Q1) with "Pick keys" and "Later".
- Keep every string the static tests pin (UI report 4.4).

- [ ] **Step 1: Failing tests**: extend `tests/test_web_app_accessibility_static.py` with the new aria strings (`aria-controls={usedInId}` etc.) and `tests/test_web_app_states.py` with "Saved in the vault only" — FAIL.
- [ ] **Step 2: Implement** source; `cd web-app && npm ci && npm run lint && npm run build`.
- [ ] **Step 3: Run** `python -m pytest tests/test_local_contracts.py tests/test_local_api_contract_static.py tests/test_web_app_accessibility_static.py tests/test_web_app_states.py tests/test_web_app_security.py tests/test_local_api.py -q` — PASS; run the two Playwright specs — PASS; screenshot the add-key form and a "Used in" row from `npm run dev` against the mock API and attach.
- [ ] **Step 4: Commit** source + `pushkey_web/out` + `pushkey_web/_manifest.py` together: `feat: add-and-connect screens in the web app`.

### Task 14: Documentation and whole-branch check

**Files:**
- Modify: `AGENTS.md` (MCP policy table gains `connect_key`; test baseline line), `README.md` (CLI usage), `docs/mcp-setup.md` (if not done in Task 9), `docs/local-api-v1.md` (if not done in Task 8)
- Test: full suite

- [ ] **Step 1:** Update docs; every command shown is copied from `pushkey --help` output after Task 10.
- [ ] **Step 2: Run** the full suite through `bg_progress.py run "add-and-connect full suite" -- python -m pytest -q`; read the summary line; expected `0 failed`, passed count ≥ 777 + new tests.
- [ ] **Step 3: Commit** `docs: add-and-connect usage`.
