# Storage / env-file shapes (read from real code, worktree add-and-connect, HEAD 0aed231)

All paths are relative to `<worktree>`. Probes that
were actually run are marked PROBED (script: scratchpad/probe_nested_lock.py); everything
else is from reading the code.

## 1. pushkey_env.py (127 lines, the whole public API)

```python
_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")          # :13

@dataclass(frozen=True)
class EnvMutationResult:                                                   # :16
    env_file: str; injected_names: list[str]; updated_names: list[str]
    skipped_existing: list[str]; wrote: bool
    @property changed_count -> len(injected_names) + len(updated_names)    # :24

def format_env_value(value: object) -> str                                 # :29
def sanitize_env_value(value: object) -> str                               # :43  == str(v).replace("\r","").replace("\n","")
def ensure_gitignore_env(project_dir: Path, *, write=True,
        atomic_write: Optional[Callable[[str, bytes], None]] = None) -> bool   # :47
def mutate_env_file(project_dir: str|Path, vault_entries: Mapping[str, Mapping[str, object]],
        *, key_names: Optional[list[str]] = None, update_existing: bool,   # update_existing is REQUIRED kw
        write=True, backup_existing=False,
        atomic_write: Optional[Callable[[str, bytes], None]] = None) -> EnvMutationResult   # :66
```

format_env_value (:29-40): quotes (double quotes, escapes `\\`, `\r`, `\n`, `"`) only when value is
empty, starts/ends with whitespace, or contains one of `\n \r \t space # "`. Not quoted/escaped
for `$`, `'`, `=`, backtick. None -> "".

ensure_gitignore_env (:47-63): reads `<project>/.gitignore` with strict utf-8; returns False if the
exact line `.env` is in `content.splitlines()` (no strip, no `.env*`, `/.env`, `*.env` patterns, no
git); else `new_content = (content.rstrip("\n") + "\n.env\n").lstrip("\n")`; if `write`, calls
`atomic_write(".gitignore", bytes)` (filename only, one segment) or `gitignore.write_text`. Returns
True when it changed (or would change when write=False). Only ever knows about the literal `.env`.

mutate_env_file (:66-127), how it works:
- `project = Path(project_dir).resolve()`; `NotADirectoryError` if not a dir (:76-78).
- `selected_names = key_names or list(vault_entries.keys())` (:80)  NOTE `key_names=[]` means ALL.
- Env var name == vault key name (no mapping). Value = `selected[name].get('value','')` passed through
  format_env_value. It does NOT call sanitize_env_value itself (callers do or don't, see below).
- Target is hard-coded: `env_path = project / ".env"` (:82). Reads `read_text(encoding="utf-8")`
  (no BOM handling), `.splitlines()` (:83).
- Parse: each existing line tested with `_ENV_LINE.match(line)` (no `export`, no leading whitespace,
  no quote/inline-comment parsing, multi-line values not understood). Matching names go in
  `existing_keys`. If `update_existing and key in selected` the line is replaced by
  `f"{key}={format_env_value(...)}"` and name appended to `updated` (:88-97). Every other line is
  kept byte-for-byte (minus line ending).
- New names (selected, not in existing_keys) appended at the end: blank line if last line non-empty,
  then `# Managed by Pushkey`, then `NAME=value` lines (:99-105). The header is added again on every
  run that injects something new (no check that it already exists).
- `skipped` = selected names present in file when `update_existing` is False (:107).
- If `write`: (1) `ensure_gitignore_env(project, write=True, atomic_write=atomic_write)` (:109);
  (2) if `backup_existing and env_path.exists()`: `shutil.copy2(env_path, project/.env.pushkey_backup_<YYYYmmdd_HHMMSS>)` (:110-112) -
  inside the PROJECT, every call, no pruning, not gitignored; (3) data = `"\n".join(new_lines)+"\n"`
  (CRLF files become LF, always trailing newline) written via `atomic_write(".env", data)` or
  tmp `.env.pushkey-<pid>.tmp` + `os.replace` (:113-119). The file is rewritten even if nothing changed.
- `wrote=write` (the argument), not "something changed". With `write=False` nothing is touched
  (dry run still returns names).

### Callers (all of them; grep -rn "mutate_env_file|ensure_gitignore_env")
| caller | args |
|---|---|
| pushkey.py:1139 inside `inject_env_file` (:1126) | `mutate_env_file(project_path, vault, key_names=names, update_existing=True, backup_existing=True)`; names pre-filtered by `target_env` match; whole raw vault dict passed, no sanitize |
| pushkey_cli.py:568 `cmd_inject` (:549) | `mutate_env_file(project, keys_to_write, update_existing=True, backup_existing=True)`; `keys_to_write` is a dict of vault entries (assigned to project, or whole vault with `--all`); no sanitize |
| pushkey_mcp.py:344 `inject_env` (:307) | `mutate_env_file(project, sanitized, key_names=keys, update_existing=False)`; `sanitized` = entries with `_sanitize_key_value` (same strip of \r\n); name must match `^[A-Za-z][A-Za-z0-9_]{0,255}$` (:64); allowlist check `project in meta["projects"]` (:71) |
| pushkey_local_api.py:1007 `inject_project` (:963) | `mutate_env_file(proj, safe_entries, key_names=keys, update_existing=False, write=write, atomic_write=atomic_write if write else None)`; `safe_entries` via `sanitize_env_value` (:993-996); `atomic_write` = closure over `_atomic_project_write(path, filename, data, identity)`; before it `_assert_project_target` on `.env` and `.gitignore` (:1001-1002, after `_project_identity` :998) and a `.env.is_symlink()` check (:991-992) |
| ensure_gitignore_env | ONLY called from pushkey_env.py:109. (pushkey.py:1109 has a separate dead `_ensure_gitignore_env(project_dir)` that nothing calls; so does `_atomic_write_text` at :1093.) |
inject_env_file callers (desktop): pushkey.py:6341, 6359, 7876, 7990, 8651 (the 8651 one is the second CLI at `ns.cmd == "inject"`).

Behaviour differences the spec's "they already replace the value" must respect: CLI + desktop use
`update_existing=True` (replace + backup in project); MCP + web app use `update_existing=False`
(never replace, skip existing). Only web/MCP strip newlines; CLI/desktop pass raw values, so a value
with `\n` is written as `"a\nb"` (escaped) there but `ab` (stripped) via web/MCP. A `status()` that
compares file vs vault must compare against the same transform it wrote.

Duplicate of format_env_value also at pushkey.py:917 (`_format_env_value`, same logic) - dead-ish copy.

## 2. pushkey_vault.py / pushkey_locking.py / pushkey_crypto.py

Locking (pushkey_locking.py:33-87)
```python
class FileLockTimeout(RuntimeError)                                          # :11
@contextmanager
def bounded_file_lock(path: Path, *, timeout_seconds: float = 5.0, poll_seconds: float = 0.05)  # :33
```
One-byte lock on `path` (msvcrt.locking LK_NBLCK on win32, fcntl.flock LOCK_EX|LOCK_NB elsewhere), raises
FileLockTimeout after 5 s.

Vault locks (pushkey_vault.py):
```python
_VAULT_WRITE_LOCK = threading.RLock()                                        # :39
class VaultData(dict):  _pushkey_revision = None                             # :42  (sha256 of vault.enc bytes)
class VaultConflictError(RuntimeError)                                       # :48
class VaultBusyError(RuntimeError)                                           # :52  ("vault_lock_failed")
def _cross_process_lock()      # bounded_file_lock(VAULT_DIR/".vault.lock"), FileLockTimeout -> VaultBusyError   :56
def _vault_write_guard()       # `with _VAULT_WRITE_LOCK, _cross_process_lock()`                                   :66
def _current_encrypted_vault_revision() -> bytes   # sha256(_read_vault_bytes())                                   :73
```
No public lock helper: `_vault_write_guard` / `_cross_process_lock` are underscore-private (pushkey_health
imports `_vault_write_guard` and `_current_encrypted_vault_revision` anyway, pushkey_health.py:17).
**Config has no lock at all** (no `.config.lock`; `save_config` is not under `_vault_write_guard`).
The only config guard is the web app's in-process `app.state.project_lock = threading.RLock()` (pushkey_local_api.py:426).

**PROBED: the vault lock is NOT re-entrant across the two layers.** Holding `_vault_write_guard()` and calling
`save_vault(...)` inside raised `VaultBusyError vault_lock_failed` after 5.0 s (RLock re-enters, but the second
`bounded_file_lock` opens a new handle and contends with the first). So `pushkey_connect` cannot "hold the vault
lock across reload-change-save" using what exists; it must use the optimistic revision check (below) and
reload+retry on VaultConflictError, or a new lock-held save function must be added to pushkey_vault.

Load / save signatures
```python
def load_vault(password) -> tuple                                             # :338  -> (VaultData, vault_key) ; (None, None) on wrong password; ({}, None) if no file
def load_vault_with_key(vault_key: bytes) -> tuple                            # :375  -> (VaultData, vault_key) ; (None, None) on ANY failure (bare `except Exception`)
def save_vault(vault, password, *, vault_key=None, recovery_code=None, expected_revision=None)   # :407
def save_vault_with_key(vault, vault_key: bytes, *, expected_revision=None)   # :495  (V3 only; password slots untouched)
def load_config()                                                             # :541
def save_config(config)                                                       # :566
```
- load_vault raises VaultFormatError / VaultIntegrityError / VaultUnsupportedKDFError (re-raised) or
  `VaultIntegrityError("corrupted:...")` for anything else (:367-372). The returned object is a `VaultData`
  whose `_pushkey_revision = sha256(raw)` (:363-365). PROBED: `connections` list of dicts round-trips intact.
- Stale-save detection (save_vault :411-417): under `_vault_write_guard`,
  `expected = expected_revision or getattr(vault, "_pushkey_revision", None)`;
  existing file and expected is None -> `VaultConflictError("expected_revision_required")`;
  `sha256(existing_raw) != expected` -> `VaultConflictError("stale_vault_revision")`. PROBED: loading twice, saving
  the first, then the second raises `VaultConflictError stale_vault_revision`. After a successful save the
  VaultData's `_pushkey_revision` is updated (:486-487), so the same in-memory object can be saved again.
  save_vault_with_key does the same check with `secrets.compare_digest` (:503-507).
  A plain `dict` (not VaultData) has no revision: fine when the file does not exist yet, else
  `expected_revision_required`.
- save_vault with an existing V3 file REQUIRES `vault_key` or `recovery_code` else `VaultFormatError("v3_save_requires_vault_key")` (:418).
- Every successful save: rolling backup `vault_backup_<ts>.enc`, keeps newest 3 (:249-262, :481, :485); invalidates
  health.json under the lock (:484 -> pushkey_health.invalidate_..._under_vault_lock). Callers then call
  `publish_saved_vault(vault)` to republish (see 3).
- Validation on both load and save (`_validate_vault_schema` :124-175): top-level `_schema` > 3 -> "future_vault_schema";
  every record must be a dict; non-`_`-prefixed names need a str `value` (or `current`); `projects` must be a list of
  str (<=10 000); every other field value goes through `validate_value` (depth <= 8, str <= 1 MB, list <= 10 000,
  dict <= 1 000 keys, scalars only int/float/bool/None). A `connections: [{project,file,var,added}]` list of
  str-valued dicts passes; **no schema bump needed**. Names starting with `_` skip the `value` check (that is how a
  `_meta` entry would pass).
- Serialisation: `_serialize_vault` -> `{"_schema": 3, "keys": vault}` (pushkey_crypto.py:351); `_deserialize_vault`
  returns `data["keys"]` or, for old files, the dict itself (:355). `_migrate_vault` only sets `_schema` (:339-348).

Config (pushkey_vault.py:541-573)
```python
def load_config():
    if not _s.CONFIG_FILE.exists(): return {"projects": {}}
    raw = _s.CONFIG_FILE.read_bytes()
    try:  key=_config_key(); plaintext=AESGCM(key).decrypt(raw[:12], raw[12:], None); return json.loads(plaintext)
    except Exception: pass
    if raw.lstrip()[:1] == b"{":   # legacy plaintext -> migrate (save_config) and return
        ...
    return {"projects": {}}
def save_config(config):
    ... nonce+AESGCM(json.dumps(config, indent=2)) -> CONFIG_FILE.with_suffix(".tmp") -> os.replace
```
- Failure behaviour (PROBED): missing file AND garbage/undecryptable file both return `{"projects": {}}` silently
  (no exception, no log). Anything else in config (e.g. `sso_settings`, desktop `projects` entries) is lost from that
  returned dict, and a later `save_config(that_dict)` would overwrite the real file. Decrypted JSON is returned
  unvalidated (could be a list).
- No revision/conflict check, no lock; tmp name is fixed `config.tmp` (two concurrent writers share it).
- Config key: `_config_key()` = pbkdf2(b"pushkey-config-key", salt) cached in module global `_CONFIG_KEY_CACHE`
  (pushkey_crypto.py:445-452); not reset by conftest.
- `log_event(message: str)` (pushkey_crypto.py:431): best-effort encrypted audit line, never raises; use for the audit event (names only).

Save helpers per entry point (all call save then publish_saved_vault; none catches VaultConflictError):
- CLI `_save_and_publish(vault, password, *, vault_key=None, recovery_code=None)` pushkey_cli.py:376 (password None -> `save_vault_with_key`).
- MCP `_save_session_vault(vault)` pushkey_mcp.py:122 (returns "health_publication_failed" or None).
- Web `_save(sess, response=None)` pushkey_local_api.py:699 (see 4).
- Desktop `save_vault_and_publish(vault, password, *, vault_key=None, recovery_code=None)` pushkey.py:158; `write_health_sidecar(vault)` wrapper pushkey.py:144.
- `VaultConflictError` is not imported anywhere outside pushkey_vault.py (grep: only a docstring mention at pushkey_local_api.py:740), so a conflict surfaces as an unhandled exception / FastAPI 500 today.

## 3. pushkey_health.py

```python
class HealthSidecarError(RuntimeError)                      # :34
class HealthSchemaError(HealthSidecarError)                 # :38
class HealthUnavailableError(HealthSidecarError)            # :42
class HealthPathError(HealthUnavailableError)               # :46
class HealthBusyError(HealthUnavailableError)               # :53
def publish_saved_vault(vault, *, generated_at=None)        # :425
    revision = getattr(vault, "_pushkey_revision", None)
    if not isinstance(revision, bytes): raise HealthUnavailableError("health_vault_revision_missing")
    return write_health_sidecar(vault, generated_at=generated_at, expected_vault_revision=revision)
```
- Needs a `VaultData` whose revision still equals the file's (else `HealthUnavailableError("health_vault_changed")`);
  it takes `_vault_write_guard()` itself, so call it AFTER save_vault returns, never inside a held guard. Callers catch
  `HealthSidecarError` (+ `VaultBusyError` in web/MCP/desktop; the CLI catches only HealthSidecarError, pushkey_cli.py:385).
- Fields read per entry (build_health_document :211-236): only `rotated`, `created`, `first_used`, `provider`
  (+ `health_status_at` reads the same). Records that are not a `Mapping` or whose name fails
  `^[A-Za-z_][A-Za-z0-9_]{0,127}$` (ASCII) are skipped; provider must be printable ASCII <= 64 bytes else None.
  **An extra `connections` list (or any other field) is ignored - cannot break health.** An underscore name is NOT
  skipped (the regex allows a leading `_`), so a `_meta` entry would be published as a key.

## 4. pushkey_local_api.py helpers (module level: 290-398; closures: 699-770)

```python
def _canonical_project_path(raw: str, *, must_exist: bool = True) -> str          # :290
```
Rejects empty / NUL / control chars (HTTPException 400 "invalid project path"); must be absolute (400 "project path must be
absolute", after `expanduser()`); `resolve(strict=must_exist)` OSError/RuntimeError -> 400; if must_exist and not a dir ->
400 "project directory not found". Returns `str(resolved)`. Pure pathlib except for the HTTPException.
```python
def _is_link_or_reparse(path: Path) -> bool                                       # :306
```
lstat; FileNotFoundError -> False; symlink or `FILE_ATTRIBUTE_REPARSE_POINT` (0x400) -> True. Other OSError propagates
(pushkey_health.py:60 has its own copy that raises HealthPathError instead). Pure.
```python
def _project_identity(project: Path) -> tuple[int, int]                           # :316   (st_dev, st_ino) of project.stat()
def _assert_project_target(project: Path, registered: str, target: Path, expected_identity) -> None   # :321
```
Raises HTTPException: 409 "project path changed during write" (canonical(project) != registered); 400 "refusing link or
reparse-point project target" (project or target is link/reparse); 400 "project target escapes registered directory"
(`target.parent.resolve(strict=True) != Path(registered)`  <- forces target to be DIRECTLY in the project folder, so a
subfolder like `apps/web/.env.local` is refused today); 409 "project directory identity changed during write".
It only checks the project root and the target leaf, not intermediate segments.
```python
def _atomic_project_write(registered: str, filename: str, data: bytes,
                          expected_identity: Optional[tuple[int,int]] = None) -> None   # :334
```
`target = project / filename`; `mkstemp(prefix=f".{filename}.pushkey-", dir=project)` (a `/` in `filename` would
break the prefix); write+flush+fsync; re-assert target before and after; refuses a link/reparse temp file (409
"temporary project target changed"); `os.replace`; asserts again; best-effort directory fsync; always unlinks temp.
Single-segment filenames only (callers pass ".env" and ".gitignore").
```python
def _canonicalize_registered_projects(cfg: dict, vault: Optional[dict] = None) -> bool   # :369
```
For each `cfg["projects"]` key: canonical form (on HTTPException keep the raw key); two keys collapsing to one ->
HTTPException(409, "canonical project path collision"); if anything changed, replaces `cfg["projects"]` and rewrites
each vault entry's `projects` list via the replacement map. Returns changed bool. It does NOT touch any other field,
so `connections[].project` would need the same rewrite.

Closures inside `create_app()` (cannot be imported as is):
```python
def _save(sess: _Session, response: Optional[Response] = None) -> None           # :699
    if sess.password is not None: _pv.save_vault(sess.vault, sess.password, vault_key=sess.vault_key)
    else:                          _pv.save_vault_with_key(sess.vault, sess.vault_key)
    try: publish_saved_vault(sess.vault); sess.health_warning = None
    except (HealthSidecarError, VaultBusyError): sess.health_warning = "health_publication_failed"
    if sess.health_warning and response is not None: response.headers["X-Pushkey-Warning"] = sess.health_warning
def _persist_project_state(sess, mutate, *, response=None, save_when=lambda _r: True)   # :734
    with app.state.project_lock:
        cfg = load_config(); original_cfg = deepcopy(cfg); original_vault = deepcopy(sess.vault)
        cfg_bytes = CONFIG_FILE.read_bytes() if exists else None; config_written = False
        try:
            result = mutate(cfg, sess.vault)
            if save_when(result): save_config(cfg); config_written = True; _save(sess, response)
            return cfg, result
        except Exception:
            sess.vault.clear(); sess.vault.update(original_vault); cfg.clear(); cfg.update(original_cfg)
            if config_written: _restore_bytes(CONFIG_FILE, cfg_bytes)
            raise
```
Note the order: config is saved BEFORE the vault here (opposite of the spec's "vault first, then config" for connect);
a failed `_save` (incl. VaultConflictError) restores the config bytes and reverts the in-memory vault to the pre-request
copy. The vault file is never restored. `_restore_bytes` (:719) is a temp-file+replace helper.

FastAPI dependence: only the exception type (HTTPException) in `_canonical_project_path`, `_assert_project_target`,
`_atomic_project_write`, `_canonicalize_registered_projects`; `_is_link_or_reparse` and `_project_identity` are pure.
All six module-level functions could move to a plain module that raises e.g. `ProjectPathError(status, msg)` (and a thin
shim in pushkey_local_api maps it to HTTPException). `_save` and `_persist_project_state` are closures bound to `app`,
`app.state.project_lock`, `_Session` and `Response`; a plain-module version would take `(session_vault, password,
vault_key)` and a lock instead. `_Session` (:159) is a plain class (vault, vault_key, password, auth_method, scopes);
`health_warning` is set dynamically, not declared in `__init__`.

Other web endpoints that touch the shapes we are changing: `create_key` with `overwrite` rebuilds the entry and drops
`projects`/history (:777-796); `delete_project` removes the path only from `projects` (:910-924; connections would be
left dangling); project registry value in this app is `{name, created}` keyed by canonical path (:900-905).

## 5. Existing .env parsing elsewhere / git usage

Three separate env-line regexes plus the file-level parser:
- pushkey_env.py:13 `_ENV_LINE` (used by mutate_env_file) - strict, name + raw rest, see 1.
- pushkey_cli.py:371 `_ENV_LINE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')` - identical pattern, used only by
  `cmd_import(args, vault, password, vault_key=None)` pushkey_cli.py:578-:  strips each line, skips `#`/blank, name `.upper()`,
  value `.strip().strip('"').strip("'")`; no `export`, no inline comments, no escape handling; skips names already in vault;
  builds entries with provider via `detect_provider`, `env:"all"`, `projects:[]`.
- pushkey.py:933 `_ENV_LINE_RE` (richer: optional `export `, double/single-quoted values, trailing ` # comment`),
  pushkey.py:971 `_parse_env_line(raw_line) -> (NAME_UPPER, value) | None` (unquotes + `\n \r \t \"`; ALSO accepts
  `Label: value` lines, and upper-cases the name!), pushkey.py:1000 `_parse_env_file(path) -> (entries, errors)` with
  entries `{name, value, line, raw_line, secret}`; adds file-name prefix for "spaced key" formats, skips empty values.
  Callers: pushkey.py:6118 and :6196 (import-folder / file-picker flows). It lives in pushkey.py (imports customtkinter at
  module top), so the CLI/MCP/web cannot import it without pulling the GUI; `_parse_env_line` upper-cases names, which
  is wrong for suggesting `NEXT_PUBLIC_x`-style names "as found".
- No parser exists that returns names in original case from `.env.example`. For `suggest()` we need a new tiny
  function (names only; never read values) or move `_ENV_LINE_RE` into pushkey_env.
- `git check-ignore` / `git ls-files`: **none anywhere** (grep over .py/.js/.ts/.ps1/.sh/.yml). Only git use:
  pushkey.py:7191 `subprocess.run(["git","rev-parse","--git-dir"], cwd=root, capture_output=True, timeout=5)` and :7196
  `git log --all -p ...` (desktop leak scan; list-form argv, no shell). scripts/verify_release_branch_protection.py:85
  `git show`. So the spec's `git check-ignore -q`, `git ls-files --error-unmatch` are new subprocess code.

## 6. pushkey_providers.py

```python
def detect_provider(key_name, key_value="")            # :85  -> provider name str | None
def provider_supports_multi_key(provider_name: str) -> bool   # :98
PROVIDERS = _load_providers()                           # :170 (module global; update_providers_from_web rebinds it)
```
detect_provider: lower-cases the name, then returns the first provider (dict order) with any `pattern in name_lower`
(plain substring, NOT regex); else longest-first `value.startswith(prefix)`. First match wins, so order matters
(e.g. "aws"/"gh_"/"google" are loose substrings). `NEXT_PUBLIC_SUPABASE_ANON_KEY` -> Supabase.

Source of data: `_BUNDLED_PROVIDERS` dict literal in pushkey_providers.py:16 merged with `~/.pushkey/providers.json`
cache (`{"providers": {...}}`, :48-56). The repo-root `providers.json` is only the remote registry mirror
(fields `_version`, `_updated`, `providers`, 28 entries); it is not read at runtime.
Real entries (identical shape in both):
```
"Supabase": {"url": "https://supabase.com/dashboard", "prefix": "eyJ", "category": "Database", "patterns": ["supabase"], "rotation_days": 180, "multi_key": false}
"OpenAI":   {"url": "https://platform.openai.com/api-keys", "prefix": "sk-", "category": "AI", "patterns": ["openai", "gpt"], "rotation_days": 90, "multi_key": true}
```
There is NO function that returns a provider's name patterns; callers must read `PROVIDERS[name]["patterns"]` (list of
lower-case substrings) directly. Patterns only describe the *vault key name*; there is nothing about env-var shapes
(`NEXT_PUBLIC_`, `*_URL`, service-role vs anon) - ranking suggestions has to be built in `pushkey_connect`. Keys that
"must stay server-side" (spec 5.5 warning) are not flagged in providers.json either.
Note AGENTS.md says "regex patterns"; the code is substring matching.

## 7. pushkey_shared.py path constants (:9-25) and where env-backups goes

```
VAULT_DIR        = Path.home() / ".pushkey"
VAULT_FILE       = VAULT_DIR / "vault.enc"
SALT_FILE        = VAULT_DIR / ".salt"
CONFIG_FILE      = VAULT_DIR / "config.json"
LOG_FILE         = VAULT_DIR / "pushkey.log"
HEALTH_FILE      = VAULT_DIR / "health.json"
PROVIDERS_CACHE  = VAULT_DIR / "providers.json"
IMPORT_DIR       = VAULT_DIR / "import"
MFA_FILE=.mfa  LICENSE_FILE=.license  TOKEN_FILE=.token  FIDO2_FILE=.fido2  SSO_FILE=.sso
LEASES_FILE      = VAULT_DIR / "leases.json"
AGENT_TOKENS_FILE= VAULT_DIR / "agent_tokens.enc"
HEALTH_PORT = 7654 ; VAULT_SCHEMA_VERSION = 3 ; ENV_LEVELS = ["all","dev","staging","prod"]
```
Lock files created beside them (not constants): `.vault.lock` (pushkey_vault.py:60), `.health.lock` (pushkey_health.py:92).
No `env-backups` constant or directory exists yet (grep). Add `ENV_BACKUPS_DIR = VAULT_DIR / "env-backups"` here:
conftest derives its redirect list from every `Path` attribute of pushkey_shared under the real VAULT_DIR
(tests/conftest.py:68-89), so a new constant is auto-redirected to tmp_path in all tests with no conftest change.
`ensure_vault_dir()` (:137) creates VAULT_DIR (0o700) and IMPORT_DIR only; a backups dir must be created by the new code
(0o700, and files 0o600; the vault code does `os.chmod(...,0o600)` best-effort).

## 8. tests/conftest.py and test helper patterns

conftest.py (112 lines):
- `pytest_configure` (:18) narrows `--basetemp=.pytest_tmp` (pytest.ini) to `.pytest_tmp/s<pid>` and prunes stale `s*` dirs
  older than 6 h (:46).
- `REAL_VAULT_DIR = pushkey_shared.VAULT_DIR` captured at import (:65); `vault_path_attributes(module)` (:68) returns every
  Path attribute of pushkey_shared at/under it.
- ONE autouse fixture `isolate_vault_paths(tmp_path, monkeypatch)` (:92-112): monkeypatch.setattr on every such attribute
  (VAULT_DIR -> `tmp_path` itself, others -> `tmp_path/<relative>`), and resets `pushkey_tiers._LICENSE_CACHE = None`
  before and after.
- **VAULT_DIR == tmp_path.** A test that makes a project folder with `tmp_path` directly shares the dir with vault.enc,
  config.json, `.vault.lock`; existing tests always use a subfolder (`tmp_path/"myproject"`). env-backups would be
  `tmp_path/"env-backups"`.
- RULE: never call `monkeypatch.undo()` - it also undoes the conftest path isolation and points CONFIG_FILE/VAULT_FILE
  back at the real ~/.pushkey. Use a scoped `with monkeypatch.context() as patch:` (example tests/test_config_storage.py:17-27).
- Not reset by conftest: `pushkey_crypto._CONFIG_KEY_CACHE` and `_LOG_KEY_CACHE` (process-wide, salt-derived), `PROVIDERS`.

Helper patterns (create vault + config + unlock):
- tests/test_cli.py (:23-70): module autouse `patch_vault` re-patches paths and sets `PUSHKEY_MASTER`; `_vault_with_key()` :44 builds
  a plain dict entry `{value, created, rotated, provider, env, projects, notes, rotation_count}`; tests call `cli.cmd_*(Namespace(...),
  vault, PASSWORD)` directly with the in-memory dict (e.g. `test_cmd_inject_all_flag_writes_env` :458: `project = tmp_path/"myproject";
  project.mkdir(); cli.cmd_inject(Namespace(project=str(project), all=True), vault, PASSWORD)`). `_subprocess_env` :53 for real CLI runs.
- tests/test_mcp.py: `_fresh_mcp()` :5 (drops and re-imports `pushkey_mcp`, `_SESSION` is a module dict);
  `test_inject_env_writes_file` :284 does `save_vault(vault, "pw")` (from pushkey_vault, first save needs no revision), then
  `mcp_mod._unlock("pw")`, then `mcp_mod.inject_env(str(project_dir), keys=[...])`; `_seed_vault_with_key(tmp_path, monkeypatch, ...)` :497
  also patches `pushkey_tiers.current_tier` to "pro". Several tests re-patch VAULT_DIR etc. by hand (redundant with the autouse).
- tests/test_local_api.py: `fresh_app` :21 (env `PUSHKEY_LAUNCH_TOKEN`, `PUSHKEY_LOCAL_PORT=0`, reload module), `client` :31 (TestClient),
  `auth` :36 (POST /api/bootstrap -> bearer), `_seed_vault(password, recovery, keys)` :45 (writes `encrypt_data_v3` blob straight to
  `_s.VAULT_FILE`), `unlocked` :346 (POST /api/unlock {"password":"master-pw"}).
- Config in tests: tests/test_config_storage.py:10 `CONFIG = {"projects": {...}}` + `pushkey_vault.save_config/load_config`;
  tests/test_multi_project.py:24 uses the DESKTOP shape `{"projects": {"project1": {"path": ..., "keys": [...]}}}`.
- tests/test_env_injection.py tests `pushkey.inject_env_file(tmp_path, vault, ...)` directly (imports `pushkey`, i.e. needs customtkinter).

## Surprising / risky (read before writing the plan)

1. **Nested vault lock deadlocks** (PROBED): `save_vault` re-takes `.vault.lock`; wrapping reload+mutate+save in
   `_vault_write_guard()` raises VaultBusyError after 5 s. The spec's "owns the reload-change-save cycle under the vault lock"
   cannot be built from existing helpers; use load_vault -> mutate -> save_vault and retry once on VaultConflictError
   (revision check works, PROBED), or add a `save_vault`-variant that assumes the guard is held.
2. **Config has no lock, no revision, and fails open**: `load_config()` returns `{"projects": {}}` for a missing OR corrupt file,
   so read-modify-write of config can silently wipe projects (and `sso_settings` etc.). Config key `projects` has two incompatible
   shapes today: web app + CLI repl: `{<canonical path>: {name, created}}` (pushkey_local_api.py:902-905, pushkey_cli.py:1289-1292) vs desktop:
   `{<name>: {path, keys, added, target_env}}` (pushkey.py:7868-7873). `pushkey_cli._project_summary` (:972) reads the path-keyed shape.
3. **Two (really four) env parsers**: pushkey_env `_ENV_LINE`, pushkey_cli `_ENV_LINE` (same regex), pushkey.py `_ENV_LINE_RE`/`_parse_env_file`
   (GUI module, upper-cases names, accepts `Label: value`). pushkey_env's regex misses `export FOO=bar` and indented lines, so an existing
   `export FOO=...` line is not seen and a duplicate `FOO=` is appended; a UTF-8 BOM hides the first variable.
4. **Backups pollute the project**: `.env.pushkey_backup_<ts>` copies (mutate_env_file :110-112) are created on every CLI/desktop inject, hold secrets,
   are never pruned, and `.gitignore` only gets `.env` (so `.env.local` and the backups are NOT ignored). `ensure_gitignore_env` is exact-line `.env` only.
5. `key_names or list(vault_entries)` treats an empty list as "all"; env var name = vault key name with no identifier validation inside pushkey_env
   (MCP validates `^[A-Za-z][A-Za-z0-9_]{0,255}$`; CLI/desktop do not; health skips names > 127 chars or non-ASCII).
6. CLI/desktop write raw values (newlines escaped in quotes), web/MCP strip newlines first: any `status()` comparison must use one canonical transform.
7. `_atomic_project_write` and `_assert_project_target` refuse subfolder targets (parent must equal the project root; mkstemp prefix uses the filename);
   they check only root + leaf for links, not intermediate segments. Generalising them is required for `apps/web/.env.local` and the spec's per-segment rule.
8. Vault-entry consumers that would misbehave with new fields: none break on an extra `connections` list (health reads 4 fields; web list_keys, MCP list_keys
   build explicit field dicts; `validate_value` accepts it). Things that DROP it: every "rebuild the entry" site replaces the whole dict:
   pushkey.py:5879, 6075, 6166, 6251, 8269; pushkey_cli.py:397, 599, 1195; pushkey_mcp.py:280; pushkey_local_api.py:785 (create with overwrite).
   Things that leave it stale: `delete_project` / `unassign` / `_canonicalize_registered_projects` only edit `projects`.
9. Only the web app (pushkey_local_api.py:652,672,779...) and desktop skip `_`-prefixed vault names; CLI, MCP and health do not (grep). Confirms the spec's "no `_meta` in the vault".
10. `VaultConflictError` is never caught by any entry point; `publish_saved_vault` must run after save and outside any held guard; the CLI's `_save_and_publish`
    does not catch VaultBusyError from it (web/MCP/desktop do).
11. New module registration points (a new `pushkey_connect.py` must be added): build_exe.py:17-21 hidden imports, Pushkey.spec:6 (hiddenimports list, stale: no pushkey_locking/health),
    pyproject.toml:52 `py-modules`, scripts/public_export.py:25 file allowlist.
12. Dead desktop code: pushkey.py:1093 `_atomic_write_text`, :1109 `_ensure_gitignore_env`, :917 `_format_env_value` (duplicates of pushkey_env helpers).
13. Test setup: VAULT_DIR is `tmp_path` itself; never `monkeypatch.undo()`; `tmp_path`-level project folders collide with vault files - always use a subfolder.
