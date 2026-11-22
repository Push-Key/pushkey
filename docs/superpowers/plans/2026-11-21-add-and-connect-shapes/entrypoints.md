# Entry-point shapes for add-and-connect (read-only mapping)

Worktree: <worktree>, branch feat/add-and-connect, HEAD 0aed231.
All line numbers are in that worktree. "unchecked" = not probed. Nothing was run; this is a read of the code.
Files: LA = pushkey_local_api.py (1393 lines), MCP = pushkey_mcp.py (647), CLI = pushkey_cli.py (1566),
AT = pushkey_agent_tokens.py (190), ENV = pushkey_env.py (127), VAULT = pushkey_vault.py.

## A. pushkey_local_api.py

### A1. Session, auth, base classes

- `StrictBody(BaseModel)`, `model_config = ConfigDict(extra="forbid")`: LA:76-77. Unknown JSON fields are a 400.
- No `@field_validator` anywhere in LA (grep). All constraints are `Field(...)` bounds/patterns/Literals.
- Validation failures become `400 {"detail":"invalid request","fields":[...]}` (never echoes input): LA:434-441.
- `_Session` LA:159-212. Fields set in `__init__`: `vault: Optional[dict]`, `vault_key: Optional[bytes]`,
  `password: Optional[str]`, `auth_method: str` ('none'|'password'|'recovery'|'agent_token'), `scopes: list[str]`
  (only meaningful for agent_token), `unlocked_at`, `last_activity`, `autolock_seconds` (900 default, LA:62).
  Properties: `locked` (autolock side effect, LA:171-178), `can_write` = unlocked and auth_method == "password" (LA:180-182).
  Methods: `unlock(vault, vault_key, password, *, method, scopes=None)` LA:184-200, `touch`, `lock`.
  `health_warning` is NOT declared in `__init__`; `_save` assigns it (LA:712,715).
- One session per process: `app.state.session = _Session()` LA:427. `app.state.project_lock = threading.RLock()` LA:426.
  `app.state.auth_lock` LA:425. Browser bearer tokens live in `app.state.sessions` (separate from the vault session).
- `require_token` (inner fn) LA:455-467: bearer must be a session token from `/api/bootstrap` (LA:552-574).
  `require_unlocked` LA:469-474: 423 "vault locked", else `sess.touch()` and returns the session.
  `require_scope(scope)` LA:476-498 (factory, returns `_check(sess = Depends(require_unlocked))`):
  - agent_token session: needs `scope in sess.scopes`, else 403 "agent token missing required scope: <scope>"; returns sess
    WITHOUT looking at `can_write`.
  - password/recovery: `read` always passes; any other scope needs `sess.can_write` else 403 "write requires master-password unlock".
  - It takes ONE scope string. "write+inject" (spec 5.6) needs two Depends or a new variant.
  `require_writable` LA:694-697 (password only) is used just for `/api/agents` create/delete.
- How a route gets the session: parameter `sess: _Session = Depends(require_scope("write"))` plus
  `_: None = Depends(require_token)`; e.g. LA:777. There is no module-level getter; tests reach it via `fresh_app.app.state.session`.
- Unlock: `POST /api/unlock` LA:601-639; a password starting `pk_agent_` goes through `authenticate_token` +
  `load_vault_with_key`, `sess.unlock(vault, vk, None, method="agent_token", scopes=scopes)` LA:606-623.

### A2. Request models (all `StrictBody`) LA:80-148

| Model | Fields |
|---|---|
| KeyCreate LA:85-91 | name `str` 1..256 pattern `^[A-Za-z][A-Za-z0-9_]*$`; value 1..65536; provider `Optional[str]` <=128; env `Literal["dev","test","staging","prod","all"]="dev"`; notes <=4096 default ""; overwrite `bool=False` |
| KeyUpdate LA:94-97 | provider, env (same Literal) , notes: all Optional |
| RotateBody LA:100 | new_value 1..65536 |
| BackupBody LA:104 | backup_value 1..65536 |
| ProjectCreate LA:108-110 | path 1..4096; name Optional <=256 |
| ProjectAssign LA:113 | keys `list[str]` max 512 (used for assign AND unassign; `path` is a QUERY param) |
| InjectBody LA:117-119 | keys `Optional[list[str]]` max 512; env Literal default "all" |
| AgentCreate LA:127-129 | name 1..128; scopes `list[Literal["read","write","inject","rotate"]]` 1..4 |
| UnlockBody LA:80-82 | password Optional 1..4096; recovery_code Optional 1..256 |
| InitBody LA:132-134 | password 8..4096; recovery_code Optional <=256 |
| AddRecoveryBody LA:137-138 | password 1..4096 |
| RekeyBody LA:141-143 | recovery_code 1..256; new_password 8..4096 |
| ImportBody LA:146-147 | blob_b64 1..3 MiB |
| ProviderDetect LA:122-124 | name 1..256; value `""` <=65536 |

### A3. Save helpers

- `_save(sess, response=None)` LA:699-717: imports `pushkey_vault` at call time (tests monkeypatch `pushkey_vault.save_vault`).
  `sess.password is not None` -> `save_vault(vault, password, vault_key=sess.vault_key)`; else `save_vault_with_key(vault, vault_key)`.
  Then `publish_saved_vault(vault)`; catches `(HealthSidecarError, VaultBusyError)` -> sets
  `sess.health_warning="health_publication_failed"` and header `X-Pushkey-Warning` (never in the JSON body).
  Does NOT catch `VaultConflictError` (stale in-memory revision) -> propagates as a 500 (tests use `pytest.raises`, LA tests:630,660).
- `_persist_project_state(sess, mutate, *, response=None, save_when=lambda _r: True)` LA:734-770, under
  `app.state.project_lock`: `cfg = load_config()`; deep copies of cfg and `sess.vault`; `mutate(cfg, sess.vault)`;
  if `save_when(result)`: `save_config(cfg)` then `_save(sess, response)`. On any exception: restores in-memory vault and cfg,
  and restores config bytes only if it wrote them (`_restore_bytes` LA:719-732). The vault FILE is never restored (deliberate, LA:740-745).
  Returns `(cfg, result)`. Config is written BEFORE the vault; no vault lock is held across the two writes.
- Plain key routes (create/update/delete/rotate/backup/promote) mutate `sess.vault` then call `_save`; NO in-memory rollback
  if `_save` raises (only `_persist_project_state` rolls back).
- `_now_date()` LA:772-774 = `%Y-%m-%d` (dates, not datetimes). Config project `created` is also a date (LA:904).

### A4. Routes under /api/keys and /api/projects

All routes also need `Depends(require_token)`. Scope in brackets.

| Route | Scope | Mutates / saves | Success body | Errors |
|---|---|---|---|---|
| GET /api/keys LA:648-668 | read | nothing | `{"keys":[{name,env,rotated,added,provider,dual_rotation,has_backup,history_count,team_role,masked}],"count"}` (no `projects`, no connections) | 423 |
| GET /api/keys/{name} LA:670-690 | read | nothing | `{name,value(PLAINTEXT),env,rotated,added,provider,dual_rotation,next_value,next_added,history,projects,notes}` | 404 |
| POST /api/keys LA:776-795 (201) | write | `sess.vault[name] = {...}` then `_save` | `{"name","provider","env"}` | 409 `key '<n>' exists; pass overwrite=true to replace` (LA:781-782); 400 if name starts "_" (unreachable: pattern forces a letter) |
| PATCH /api/keys/{name} LA:797-809 | write | provider/env/notes, `_save` | `{name,provider,env,notes}` | 404 |
| DELETE /api/keys/{name} LA:811-816 (204) | write | `del vault[name]`, `_save`; does not touch config | empty | 404 |
| POST /api/keys/{name}/rotate LA:818-829 | write | history insert (max 10), value, rotated=date; `_save` | `{"name","rotated","history_count"}` | 404 |
| POST /api/keys/{name}/backup LA:831-842 | write | next_value, next_added, dual_rotation=True; `_save` | `{"name","next_added","dual_rotation":true,"provider_supports_multi_key"}` | 404 (no tier check) |
| POST /api/keys/{name}/promote LA:844-859 | write | history insert, value=next_value, rotated, next_*=None; `_save` | `{"name","rotated"}` | 404; 400 "no backup key staged" |
| GET /api/projects LA:863-891 | read | for a `can_write` session it runs `_persist_project_state(canonicalize, save_when=bool)` (may rewrite config); else works on deep copies | `{"projects":[{"path","name","keys","created"}],"count"}`; `keys` = vault names whose `projects` contains the path | 409 "canonical project path collision" |
| POST /api/projects LA:893-907 (201) | write | `_persist_project_state`: `config.projects[canonical]={"name": body.name or basename,"created": date}` | `{"path","name"}` | 400 invalid/relative/missing dir; 409 "project exists" |
| DELETE /api/projects?path= LA:909-924 (204) | write | removes config entry and the path from EVERY key's `projects` | empty | 404 "project not found" |
| POST /api/projects/assign?path= LA:926-942 | write | appends canonical path to each key's `projects`; `_persist_project_state` | `{"path","assigned":[...]}` | 404 project not registered; 400 `keys not in vault: [...]` |
| POST /api/projects/unassign?path= LA:944-960 | write | removes path from keys' `projects` (silently ignores unknown keys) | `{"path","unassigned":[...]}` | 404 |
| POST /api/projects/inject?path=&write=true LA:962-1020 | inject | no vault/config change except a canonicalisation save; writes `.env` and `.gitignore` | `{"injected":[names],"skipped_existing":[names],"env_file":<abs path str>,"wrote":bool}` | 404 not registered; 400 keys not in vault; 400 ".env symlink"; 400/409 from `_assert_project_target` |

Details of create_key (LA:776-795): `provider = body.provider or detect_provider(name, value) or "Unknown"`; the entry is rebuilt as
`{value, created=date, rotated=date, provider, env, projects: [], notes}`. With `overwrite=true` this REPLACES the whole entry:
`projects`, `history`, `next_value`, `dual_rotation`, `rotation_count`, and any future `connections` are dropped (spec section 2 bullet confirmed).

Details of inject (LA:962-1020), step by step:
1. `path = _canonical_project_path(path)` (LA:290-303): rejects empty/NUL/control chars, `expanduser()`, must be absolute, `resolve(strict=True)`, must be a dir; all 400.
2. `_persist_project_state(canonicalize_registered_projects, save_when=bool)` LA:966-972 (saves only if canonicalisation changed something).
3. 404 if `path not in cfg["projects"]` (registered-project check, LA:973-974).
4. keys: `body.keys is None` -> vault keys whose `projects` contains path; else `body.keys` (must exist in vault, 400) and the
   allowlist is NOT checked for explicit keys (LA:977-984). A registered project + inject scope can therefore write any vault key.
5. env filter: `body.env == "all" or key_env == "all" or key_env == body.env` (LA:986-988).
6. 400 if `<path>/.env` is a symlink (LA:990-992); values go through `sanitize_env_value` (strips CR/LF, ENV:43-44) (LA:993-996).
7. If `write`: `_assert_project_target` on `.env` and `.gitignore` (LA:1000-1002).
8. `mutate_env_file(proj, safe_entries, key_names=keys, update_existing=False, write=write, atomic_write=...)` LA:1007-1014, where
   `atomic_write(filename, data)` -> `_atomic_project_write(path, filename, data, identity)` LA:1004-1005.
   So `update_existing=False`: an existing variable is skipped and reported in `skipped_existing`.
9. `write=false` = preview (reads the file, writes nothing, `ensure_gitignore_env` not called).

The strict writer (reuse target for spec 5.4):
- `_is_link_or_reparse` LA:306-313; `_project_identity(project)` = `(st_dev, st_ino)` LA:316-318.
- `_assert_project_target(project, registered, target, expected_identity)` LA:321-331 raises HTTPException: 409 "project path changed
  during write" (re-canonicalises project), 400 "refusing link or reparse-point project target" (project or target), 400 "project target
  escapes registered directory" (`target.parent.resolve(strict=True) != Path(registered)`), 409 "project directory identity changed".
- `_atomic_project_write(registered, filename, data, expected_identity=None)` LA:334-366: mkstemp in the project dir with prefix
  `.{filename}.pushkey-`, fsync, assert, check temp not a link, `os.replace`, assert, fsync dir.
  LIMITS for the core: `filename` must be a bare name directly in the registered folder (the parent check and the mkstemp prefix both
  fail for `apps/web/.env.local`); it only pins the project folder identity, not subfolders; it raises `HTTPException` (an HTTP type)
  from inside what should be a framework-free core module; hardlink handling of an existing `.env` is unchecked (it uses `os.replace`, which swaps the directory entry).
- Tests monkeypatch `fresh_app._atomic_project_write` and the closure still picks it up because it is resolved as a module global at call time.

`mutate_env_file` contract (ENV:66-127, shared by all three):
`(project_dir, vault_entries: Mapping[name, entry], *, key_names=None, update_existing, write=True, backup_existing=False, atomic_write=None) -> EnvMutationResult(env_file, injected_names, updated_names, skipped_existing, wrote)`.
Hard-codes `project/".env"` (ENV:82) and uses the vault entry NAME as the variable name (ENV:94,105). Note `key_names or list(vault_entries)`
(ENV:80): an empty list means "all". Gitignore check is `".env" in content.splitlines()` (ENV:55). Backup writes `.env.pushkey_backup_<ts>`
next to the file (ENV:110-112) - only the CLI asks for it (`backup_existing=True`). Without `atomic_write` it writes
`.env.pushkey-<pid>.tmp` then `os.replace` (ENV:116-119), no link checks.

### A5. How tests drive the local API (tests/test_local_api.py, 1412 lines)

- `fresh_app(monkeypatch)` :20-27: sets `PUSHKEY_LAUNCH_TOKEN=test-launch-token`, `PUSHKEY_LOCAL_PORT=0`, deletes `sys.modules["pushkey_local_api"]`, re-imports, returns the module.
- `client(fresh_app)` :30-32 = `TestClient(fresh_app.app)`. `auth(client)` :35-42 = `POST /api/bootstrap` with the launch token, returns `{"Authorization": "Bearer <session token>"}`.
- `_seed_vault(password, recovery, keys)` :45-49 writes a V3 blob of `{"_schema": VAULT_SCHEMA_VERSION, "keys": {...}}` with `encrypt_data_v3` straight to `_s.VAULT_FILE`.
- `unlocked(client, auth)` :346-354: seeds `OPENAI_API_KEY` (env "prod", projects []) with password `master-pw`, recovery `PUSH-AAAA-BBBB-CCCC-DDDD` and `POST /api/unlock {"password":"master-pw"}`; returns the client.
  `unlocked_recovery` :357-365. `unlocked_with_keys` :871.
- Agent-token fixtures: `licensed_tier` :1178-1184 (`monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "team")`), `_mint_local_token` :1187-1191, `token_seed` :1194-1202,
  `token_unlocked(scopes)` :1261-1273 mints a token with those scopes, unlocks it, returns the client.
- Call style: `c.post("/api/keys", headers=auth, json={...})`, `c.post("/api/projects/assign", headers=auth, params={"path": p}, json={"keys":[...]})`, `c.delete("/api/projects", headers=auth, params={"path": p})`.
  Examples: assign :742-750, inject :803-815, inject-skip-existing :817-830, scope tests :1324-1370.
- Disk assertions use `load_vault("master-pw")[0]` and `load_config()` (:580-598). Fault injection: `monkeypatch.setattr(pushkey_vault, "save_vault", ...)` (:626, :653) and `monkeypatch.setattr(fresh_app, "publish_saved_vault", ...)` (:969-993, expects header `X-Pushkey-Warning`).
- `tests/conftest.py:92-107` autouse fixture redirects every `pushkey_shared` path under the real vault dir to `tmp_path` - so `tmp_path` IS the vault dir, and tests also create project folders as `tmp_path/<name>` (a project folder inside the vault dir). Project paths in assertions are `str(path.resolve())`.

## B. pushkey_mcp.py

### B1. Session and helpers

- `_SESSION: dict` MCP:79 with keys `vault, vault_key, password, scopes, last_activity`. Module-level, not thread safe (comment MCP:76-77). Timeout 30 min (MCP:78, `_require_unlock` MCP:142-153).
- Master password unlock MCP:90-99: `scopes = ["read","write","inject"]`. Token unlock MCP:102-115: `password=None`, `scopes` from the token. `_lock()` clears.
- `_require_scope(scope)` MCP:156-167 returns `None` or `{"error":"scope_denied","required_scope","token_scopes","hint"}`; `_require_unlock` returns `{"error":"vault_locked"|"session_expired","hint"}`. One scope per call; `connect_key` (write+inject) needs two calls.
- `_save_session_vault(vault)` MCP:122-132: password present -> `_vault.save_vault(vault, password, vault_key=...)`, else `_vault.save_vault_with_key(vault, vault_key)`; then `publish_saved_vault(vault)`; returns `None` or `"health_publication_failed"` (catches `HealthSidecarError, VaultBusyError`). Does not catch `VaultConflictError`.
  Only add_key and rotate_key put the result in the reply as `health_warning`; set_backup_key, rotate_to_backup, assign_key discard it.
- `_valid_key_name(name)` MCP:67-68 with `^[A-Za-z][A-Za-z0-9_]{0,255}$` (MCP:64). Case is preserved (no upper()).
- `_key_allows_project(meta, project)` MCP:71-72 = `project in (meta.get("projects") or [])` (exact string match).
- `_sanitize_key_value(v)` MCP:59-61 strips CR/LF.
- MCP never reads or writes config.json (grep: no `load_config`/`save_config`), so it has no notion of a registered project; `list_projects` is derived from vault `projects` lists only.
- Only audit calls: `log_event("[mcp] backup key added/enabled: NAME")` MCP:480-481 and `"[mcp] backup promoted to active: NAME"` MCP:529-530. add/rotate/assign/inject are not logged.

### B2. Tools (`@mcp.tool()`; FastMCP returns the plain function, so tests call them directly)

| Tool (MCP line) | Scope | Success | Failure |
|---|---|---|---|
| unlock_vault(password) :170 | - | `{"success":True,"key_count","auth":"master_password"|"agent_token"[,"scopes"]}` | `{"success":False,"error":...}` |
| lock_vault() :184 | - | `{"success":True}` | |
| list_keys(env=None, provider=None, project=None) :191 | read | `{"count","keys":[{name,provider,env,projects,created,rotated,notes}]}` (project filter = exact string in `projects`) | scope/lock error dicts |
| get_key(name) :218 | read | `{name,value,provider,env,notes,warning}` | `{"error":"invalid key name"}`, `{"error":"key 'X' not found"}` |
| add_key(name, value, provider=None, env="dev", notes="", overwrite=False) :249 | write | `{"success":True,"name","provider","warning"[,"health_warning"]}` | `{"success":False,"error":"invalid key name"}`; `... already exists; pass overwrite=True to replace` |
| inject_env(project_path, keys=None) :306 | inject | `{"success":True,"injected_count","injected_names","skipped_count","skipped_existing"}` (no file path, no `wrote`) | see below |
| check_health(rotation_threshold_days=90) :354 | read | `{"total","stale_count","healthy_count","stale_keys":[{name,provider,env,age_days}],"unknown_provider_keys","backup_missing","rotation_threshold_days"}` (MCP:380-388) | |
| rotate_key(name, new_value) :391 | write | `{"success":True,"name","rotated","warning"[,"health_warning"]}` | invalid name; `key 'X' not found` |
| set_backup_key(name, backup_value) :435 | write | `{"success":True,"name","backup_added","status":"backup_ready","warning"}` | `can_do("dual_rotation")` false -> "Dual-key rotation requires Pro or higher..." |
| rotate_to_backup(name) :498 | write | `{"success":True,"name","rotated","backup_slot":"empty","action_needed"}` | not enabled / no backup |
| list_projects() :542 | read | `{"projects":{path:{"key_count","keys":[...]}},"total"}` (from vault only) | |
| assign_key(key_name, project_path) :559 | write | `{"success":True,"key","project": <input path as given>}` | invalid name; not found |
| create_agent_token(name, scopes: list[str]) :580 | `_require_unlock` + master-password session (`_SESSION["password"]` set) | `{"success":True,"token_id","token_value","name","scopes","warning":"Store this token securely — it will not be shown again."}` (MCP:603-610) | `{"success":False,"error":"creating agent tokens requires master password auth, not an agent token"}` or the `create_token` error text |
| list_agent_tokens() :613 | `_require_unlock` only | `{"count","tokens":[{id,name,scopes,created,expires_at,last_used}]}` | |
| revoke_agent_token(token_id) :624 | `_require_unlock` + password session | `{"success":True,"revoked":id}` | `{"success":False,"error":"token '<id>' not found"}`; password-session error |

Exact plaintext warning strings (must be kept by any new tool that accepts a value; Q4 says `add_key` keeps its warning):
- add_key MCP:294-299: `"Key value entered the MCP client context and may be retained by the client, model provider, transcript, or telemetry. OK for dev/test keys. For production keys, add via local CLI: `pushkey add {name}` (hidden prompt, no LLM exposure)."`
- rotate_key MCP:423-428: `"New key value entered the MCP client context and may be retained by the client, model provider, transcript, or telemetry. OK for dev/test keys. For production keys, prefer `pushkey rotate` (CLI, getpass) or pre-stage a backup and use rotate_to_backup() so secrets never cross chat."`
- set_backup_key MCP:485-490: `"Backup value entered the MCP client context and may be retained by the client, model provider, transcript, or telemetry. OK for dev/test keys. For production, seed backups via local CLI to keep secrets off the wire, then use rotate_to_backup() (name-only) for promotion."` When the provider supports one key only (`provider_supports_multi_key` false) it is prefixed with `"Provider '<p>' may only support one active key at a time. Dual rotation works best with providers that allow multiple simultaneous keys (OpenAI, Anthropic, AWS, Stripe, GitHub, etc.).  "` (MCP:468-472, 492).
- get_key MCP:241-245 has its own warning.
- Tests assert substrings: "MCP client context" and `pushkey add NEW_KEY` (test_mcp.py:238-239), "MCP client context" and "pushkey rotate" (:441-442), "local CLI" (:523).

Behaviour that matters for the core:
- add_key overwrite (MCP:275-288): `name in vault and not overwrite` -> error; otherwise it REBUILDS the entry `{value (sanitised), created=date, rotated=date, provider, env (unvalidated free string), projects: [], notes}` - drops `projects`, `history`, `next_value`, `dual_rotation`, `rotation_count`. Provider default `detect_provider(...) or "Unknown"`.
- rotate_key (MCP:416-417): sets value and `rotated` only. No `history` insert, no `rotation_count`, leaves `next_value`/`dual_rotation` alone, no log_event.
- rotate_to_backup (MCP:523-526): value = next_value, `rotated`, clears `next_value`/`next_added`; no history entry (the old value is discarded), leaves `dual_rotation=True`, no tier check. Calls `_save_session_vault` and ignores its return. This is where `sync` would be triggered (spec 5.6).
- assign_key (MCP:570-575): `str(Path(project_path).resolve())` (non-strict: a nonexistent path is accepted), no registered-project check, no dir check, only needs `write`; saves only if the path was new.
- inject_env (MCP:313-351): `Path(project_path).resolve()`, `is_dir()` else `{"success":False,"error":"directory not found: ..."}`; `keys is None` -> all keys with the path in `projects`, error "no keys assigned to this project; pass keys=[...] explicitly" when none; invalid names; `keys not in vault`; allowlist enforced for EVERY key (`"project path is not allowlisted for keys: [...]"` + `hint`); values sanitised; calls `mutate_env_file(project, sanitized, key_names=keys, update_existing=False)` with no `atomic_write`, no symlink check, no config registration check. Existing variables are skipped.

### B3. How tests drive MCP (tests/test_mcp.py, 577 lines)

- `_fresh_mcp()` :5-8: `del sys.modules["pushkey_mcp"]; importlib.import_module("pushkey_mcp")` (resets `_SESSION`).
- Typical test: `save_vault({...plain dict...}, "pw")` -> `mcp_mod = _fresh_mcp()` -> `mcp_mod._unlock("pw")` (alias :136-139) -> call the tool function directly -> `load_vault("pw")` to assert disk state (e.g. :223-243, :284-314, :472-492).
- Most tests re-monkeypatch `_s.VAULT_DIR/VAULT_FILE/SALT_FILE/CONFIG_FILE/LOG_FILE` to tmp_path although conftest autouse already does it. Project folders are `tmp_path/...`; vault entries store `str(project_dir.resolve())`.
- Agent-token-style session without a token: `mcp_mod._SESSION.update(vault=vault, vault_key=vault_key, password=None, scopes=["read","write"], last_activity=datetime.now())` after `save_vault({}, "password", recovery_code=...)` and `load_vault("password")` (:120-140; proves both V3 slots survive a raw-key save).
- Tier gates: `monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")` (:509-510).

## C. pushkey_cli.py

### C1. argparse and dispatch (`main()` CLI:646-732)

- `--local-api-server` special case CLI:647-649 (frozen exe).
- Global options: `--password/-p` CLI:654, `--token` CLI:655-659; env `PUSHKEY_MASTER` (CLI:273), `PUSHKEY_AGENT_TOKEN` (CLI:284).
- Subcommands (sub = `add_subparsers(dest="command", required=False)`, CLI:660):
  - `add NAME VALUE [--notes]` CLI:662-665. VALUE is a REQUIRED positional (value on argv, visible in process lists/history). Not getpass. AGENTS.md and the spec ("value asked with getpass when left out, as today", spec 5.6) both describe a getpass path that does not exist for the subcommand; only `_repl_add` uses getpass (CLI:1185).
  - `get NAME [--clip/-c]` :667-669; `list [--status healthy|warning|critical] [--json]` :671-673;
  - `rotate NAME [NEW_VALUE]` (nargs="?", getpass if omitted, CLI:473-478) :675-677; `set-backup NAME` (always getpass) :679-680;
  - `delete NAME [--yes/-y]` :682-684; `status` :686; `inject [--project PATH] [--all]` :688-690;
  - `import FILE` :692-693; `init [--recovery-file]` :695-699; `app` :700; `completion {bash,powershell}` :701-702.
- Flow after parse: `command is None` -> `_pre_unlock_shell` (CLI:706-707); init/app/completion handled before unlock (CLI:709-717);
  else `vault, password, vault_key, scopes = _open_vault(args)` then `_require_command_scope(args.command, scopes)` (CLI:719-720), then a literal dict `{"add": cmd_add, ..., "import": cmd_import}[args.command](args, vault, password, vault_key)` (CLI:722-732).
- Signature of every `cmd_*`: `(args, vault, password, vault_key=None)`; `args` is an argparse Namespace; they exit via `sys.exit(code)` (EXIT_USAGE=2 for add "already exists" and a bad completion shell, 1 for most "not found" and a non-directory inject path, EXIT_INTERRUPTED=130 for set-backup missing key, EXIT_AUTH=10 for scope/auth, 0 for inject with nothing assigned).
- Things a new subcommand must also touch: `CLI_COMMANDS` list CLI:48-51 (shell completion; tests at test_cli.py:440-455), `_COMMAND_SCOPES` CLI:339-349, the dispatch dict CLI:722-732, `_REPL_COMMANDS` CLI:916-918, `_handle_repl_command` CLI:1399-1478, `_print_help` rows CLI:1515-1532 (tests check text), `_print_agent_help` scope blurbs CLI:1487-1491.
- Scope gating is fail-open for unknown commands: `required = _COMMAND_SCOPES.get(command); if required and required not in scopes` (CLI:361-362). A new command that is not added to `_COMMAND_SCOPES` is NOT gated. Values are single strings, so a write+inject command needs a different structure. tests/test_cli_agent_tokens.py:145-163 parametrise over `_COMMAND_SCOPES.items()`, so every new entry is auto-tested for allow/deny with single scopes.
- `_open_vault(args)` CLI:311-323 returns `(vault, password|None, vault_key, scopes|None)`; token sessions have `password=None`, `scopes=list`; master sessions have `scopes=None`. Wrong password -> EXIT_AUTH.
- Saves: `_save_vault_for_session(vault, password, vault_key)` CLI:326-336 (password -> `save_vault`, else `save_vault_with_key`); `_save_and_publish(vault, password, *, vault_key=None, recovery_code=None)` CLI:376-387 adds `publish_saved_vault` and returns/prints `"health_publication_failed"` (stderr) - catches `HealthSidecarError` only (not `VaultBusyError`, not `VaultConflictError`).

### C2. The cmd_* functions

- `cmd_add` CLI:390-412: `name = args.name.upper()` (CLI:391); exists -> stderr + `sys.exit(EXIT_USAGE)` (no overwrite option); `provider = detect_provider(name, args.value)` (may be None); entry `{value, created=datetime.isoformat(), rotated=None, provider, env="all", projects=[], notes, rotation_count=0}`; `_save_and_publish`; `log_event(f"cli: added {name}")`; prints `Added NAME [Provider]` (value never printed).
- `cmd_rotate` CLI:467-490: upper(); value from argv or `getpass.getpass(f"New value for {name}: ")`; history insert (max 10), `rotated=iso`, `rotation_count += 1`; `_save_and_publish`; `log_event`; prints `Rotated NAME`. Does not touch `next_value`.
- `cmd_set_backup` CLI:493-513: getpass only (`Backup value for NAME: `); sets `next_value`, `next_added=iso`, `dual_rotation=True`; saves with `_save_vault_for_session` (NO health publish), `log_event`; prints `Backup staged for NAME`. No tier check. There is no CLI command that promotes a backup (rotate-to-backup exists only in MCP and the local API `promote`).
- `cmd_inject` CLI:549-575: `project = Path(args.project or cwd).resolve()` (non-strict; `is_dir()` check); keys = vault entries whose `projects` contain `str(project)`; none -> prints "No keys assigned..." and `sys.exit(0)` unless `--all` (then every vault key, ignoring the allowlist); `mutate_env_file(project, keys_to_write, update_existing=True, backup_existing=True)` - replaces existing values, writes `.env.pushkey_backup_<ts>` in the project (the gitignore bug from spec section 2), no `atomic_write`, no symlink check, values NOT sanitised (`format_env_value` quotes CR/LF instead of stripping); `log_event(f"cli: injected {n} keys into {project}")`; prints `Wrote N key(s) to <env_file>`. Registered-project check: none (never reads config).
- `cmd_list` CLI:433-464 (`--json` rows `{name,provider,age,status,env}`), `cmd_status` CLI:538-546 (counts only). Neither shows projects or connections.
- `cmd_import` CLI:578-614: bulk add from a .env file, names upper(), skips existing, `_save_and_publish`.

### C3. Interactive shell

- `_run_repl_session(vault, password, vault_key=None)` CLI:168-207: `line.split()` (whitespace split, so a path with spaces breaks: `project add C:\My Projects\x`), `cmd = parts[0].lower()`, `rest = parts[1:]`, then `_handle_repl_command(cmd, rest, vault, password, vault_key, app_proc)` CLI:198; a `False` return ends the loop.
- Dispatch is an if-chain, not a table: `_handle_repl_command` CLI:1399-1478; numeric aliases CLI:1400 (`1 add, 2 get, 3 inject, 4 rotate, 5 projects, 6 agents, 7 security, 8 app`). Tab-complete list `_REPL_COMMANDS` CLI:916-918, completer completes key names for get/copy/rotate/delete only (CLI:948).
- `project` command CLI:1413-1424: `project add <path>` (needs >=2 tokens) -> `_repl_project_add(rest[1])`; `project assign <path> KEY...` (>=3) -> `_repl_project_assign(vault, password, rest[1], rest[2:], vault_key)`; `project inject <path>` (>=2) -> `_repl_inject(vault, password, rest[1])`. `projects` -> `_repl_projects(vault)`. `inject [PATH]` -> `_repl_inject`.
- `_repl_project_add(project_arg)` CLI:1283-1295: `Path(project_arg).resolve()` (non-strict, relative resolved against cwd, NO is_dir check, no `~` expansion); `config.projects[str(project)] = {"name": project.name, "created": datetime.isoformat()}` if new; `save_config(config)`; prints; returns the key string. Unscoped, outside any lock, no vault touched.
- `_repl_project_assign` CLI:1298-1310: calls `_repl_project_add` FIRST (so the folder is registered even when the key names turn out to be unknown), then validates names (`.upper()`), appends to each key's `projects`, `_save_vault_for_session` (no health publish, no config rollback), prints.
- `_repl_inject` CLI:1256-1280: allowlist keys only (none -> "No keys assigned"), prints project + key names, `Confirm? [y/N]`, then builds a throwaway `_A` object with `.project`/`.all=False` and calls `cmd_inject(a, vault, password)`. So the shell also overwrites values and creates backups.
- `_repl_add` CLI:1176-1202 (prompts name, getpass value, notes; env "all"; saves with `_save_and_publish`), `_repl_rotate` CLI:1205-1228 (getpass, `.strip()`s the value, unlike `cmd_rotate`).
- `_project_summary(vault)` CLI:973-992 merges `config.projects` with paths found only in vault `projects`; used by the dashboard and `_repl_projects` (CLI:1313-1324).
- SCOPE BYPASS: `_unlock_into_repl` CLI:210-213 does `vault, password, vault_key, _scopes = _open_vault(args)` and discards `_scopes`; `pushkey --token <read-only token>` with no subcommand reaches `_pre_unlock_shell` (CLI:706-707) -> "unlock" -> a REPL where add/rotate/delete/inject/project work with no scope check. `_run_repl_session` takes no scopes. test_cli.py:659-668 monkeypatches `_run_repl_session` with a 3-argument lambda `(vault, password, vault_key)`, so adding a `scopes` parameter needs that test updated.
- `_repl(args)` CLI:1552-1562 has no caller: repo-wide grep of `*.py`/`*.toml`/`*.cfg` for `_repl(` finds only `_unlock_into_repl` (CLI:210,230) and its test (test_cli.py:666); `pyproject.toml:47-49` entry points are `pushkey_cli:main` and `pushkey:main` (unreachable by name).
- `_render_stale_warnings` CLI:1073-1098 (run at shell start, CLI:174) calls `_repl_rotate(vault, password, target)` at CLI:1096 WITHOUT `vault_key`; on a V3 vault `save_vault(vault, password, vault_key=None)` raises `VaultFormatError("v3_save_requires_vault_key")` (VAULT:418-419). Read from code, not executed.

### C4. How tests drive the CLI

- tests/test_cli.py autouse `patch_vault` :24-36 sets `PUSHKEY_MASTER` and monkeypatches `pushkey_shared` VAULT_DIR/VAULT_FILE/SALT_FILE/CONFIG_FILE/LOG_FILE/HEALTH_FILE/... to tmp_path. Helpers `_empty_vault()` (plain `{}`) and `_vault_with_key()` :39-55, `PASSWORD` :20.
- In-process: `cli.cmd_add(Namespace(name=..., value=..., notes=None), vault, PASSWORD)` then `capsys.readouterr()` (:242-274); inject: `Namespace(project=str(project), all=True)` (:458-499); rotate `Namespace(name=, new_value=)`; set-backup `Namespace(name=)` with `monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: ...)` (:533-544).
  A plain-dict vault works only while no vault file exists (`save_vault` raises `VaultConflictError("expected_revision_required")` otherwise); the V3 test loads a real `VaultData` via `cli.load_vault` (:218-237). With a plain dict, `publish_saved_vault` raises `HealthUnavailableError`, which `_save_and_publish` catches and prints.
- main(): `monkeypatch.setattr(cli.sys, "argv", ["pushkey", "--token", tok, "add", "K", "v"]); cli.main()` (test_cli_agent_tokens.py:183-196, test_cli.py:564-570); parser checked by stubbing `cli._open_vault`.
- Subprocess: `subprocess.run([sys.executable, "-m", "pushkey_cli", "add", ...], env=_subprocess_env(home, password=...), cwd=ROOT, timeout=30)` with `USERPROFILE`/`HOME` pointed at an isolated dir and the vault seeded by a `python -c "from pushkey_vault import save_vault..."` subprocess (test_cli.py:58-68, :147-215).
- Shell: `monkeypatch.setattr("builtins.input", lambda _p: next(prompts))`, `_handle_repl_command` called directly (:812-826), `cli._repl_project_add(str(dir))` / `cli._repl_project_assign(vault, PASSWORD, str(dir), [names])` then `cli.load_config()` (:752-780).

## D. Agent tokens and scope checks

- Scopes are defined in AT:22 `VALID_SCOPES = {"read","write","inject"}`; docstring AT:8-12 maps read = list_keys/get_key/check_health/list_projects, write = add_key/rotate_key/assign_key, inject = inject_env. Tokens live encrypted in `AGENT_TOKENS_FILE`; 30-day expiry (AT:23); creation requires a paid tier via `max_agent_tokens` (AT:96-110) and an invalid scope returns `(False, "Invalid scopes: ...", "")` (AT:112-114).
- `authenticate_token(token_value) -> (vault_key|None, scopes, err)` AT:161-190; scopes default `["read"]` if the stored record has none (AT:187). Authenticating rewrites the token file (`last_used`).
- No "rotate" scope exists. LA:129 still lets `AgentCreate` accept `"rotate"`, which `create_token` then rejects (the route returns 403 with that text, LA:1047-1049). The CLI map reuses `write` for `rotate` (CLI:343).
- MCP: `_require_scope(scope)` MCP:156-167 per tool, master password gets `["read","write","inject"]` (MCP:97).
- Local API: `require_scope` LA:476-498 per route (see A1); read/write/inject only. `/api/unlock` with `pk_agent_...` LA:606-623.
- CLI: `_COMMAND_SCOPES` CLI:339-349 (`add/rotate/set-backup/delete/import` write; `get/list/status` read; `inject` inject) + `_require_command_scope` CLI:352-368 in `main()` only; the shell has none (C3).
- All three save agent-token sessions through `save_vault_with_key` (CLI:326-336, MCP:122-126, LA:705-709): password is None, so a token session can never use `save_vault(..., password)`.
- Spec 5.6/5.7 rules the code cannot express today: "`connect_key` needs write and inject" (MCP/LA/CLI each take one scope per call), and "an agent can connect keys only to projects a person added" (MCP has no registry, CLI/MCP assign_key accept any path).

## E. Inconsistencies the shared core must resolve

1. Project identity. LA: absolute only, `expanduser`, `resolve(strict=True)`, must be a dir, must be in `config.projects` for assign/unassign/inject (LA:290-303, LA:932, LA:973). MCP `assign_key`/`inject_env` and CLI `project add`/`cmd_inject`: non-strict `resolve()`, relative accepted (against cwd), `~` not expanded, no registry check; MCP/CLI `inject` check `is_dir`, MCP `assign_key` and CLI `project add` do not. Config entries differ: LA `created` is a date; CLI `created` is `isoformat()` datetime. Registry membership is what Q4 wants to enforce, but MCP/CLI never read the registry today.
2. Allowlist check on write. MCP enforces it for every key; LA enforces it only when `keys` is omitted (explicit `keys` skip it, LA:977-984); CLI `--all` skips it (CLI:561-562).
3. Overwrite of a value already in the file. CLI/shell: replace + `.env.pushkey_backup_*` (CLI:568-573); MCP and LA: skip (`update_existing=False`). The core needs one rule (spec Q2 says replace).
4. Overwrite of a key already in the vault. LA `overwrite=true` and MCP `add_key(overwrite=True)` rebuild the entry (drop `projects`, history, backup, rotation_count); CLI `add` refuses (no flag, EXIT_USAGE); the shell refuses too. Rotation itself differs: LA `rotate` keeps history (10) but no `rotation_count`; MCP `rotate_key` keeps neither; CLI/shell keep history and `rotation_count`; MCP `rotate_to_backup` and LA `promote` handle history differently (LA inserts, MCP does not); CLI has no promote.
5. Entry defaults. Date format: LA/MCP `%Y-%m-%d`, CLI `datetime.isoformat()` and `rotated=None`. `env`: CLI always "all"; LA/MCP default "dev" (LA validated Literal, MCP free string). `provider`: LA/MCP "Unknown" fallback, CLI None. `rotation_count`: CLI only. Name rule: CLI `upper()` with no regex; MCP regex up to 256 chars, case kept; LA regex, case kept.
6. Value sanitising. LA and MCP strip CR/LF (`sanitize_env_value`/`_sanitize_key_value`); CLI passes the raw value and relies on `format_env_value` quoting; `_repl_rotate` strips whitespace, `cmd_rotate` does not.
7. File writer. Only LA uses the strict `_atomic_project_write` + `_assert_project_target` (LA:321-366, raises HTTPException, root-only single filename, pins only the project folder). MCP and CLI go through `mutate_env_file`'s default writer with no link/reparse checks and no folder-identity pin (it reads through a `.env` symlink, `os.replace`s the link itself, and `gitignore.write_text` follows a `.gitignore` symlink; ENV:54,62,83,119). Spec 5.4 (subfolders, every segment pinned, `.env.*` names, git-tracked refusal, backups under `~/.pushkey/env-backups`) needs a new writer; `mutate_env_file` hard-codes `.env` and the vault key name as the variable (ENV:82,94,105) and its gitignore test is the exact line `.env` (ENV:55).
8. Save helpers and error handling. Three different helpers (LA `_save`, MCP `_save_session_vault`, CLI `_save_and_publish`/`_save_vault_for_session`). Health publication: LA and MCP catch `(HealthSidecarError, VaultBusyError)`, CLI catches only `HealthSidecarError`; CLI `set-backup` and `project assign` skip publication entirely; MCP set_backup/rotate_to_backup/assign_key drop the warning; LA reports it as header `X-Pushkey-Warning`, MCP as `health_warning` in the body only for add/rotate, CLI as a stderr line. None handles `VaultConflictError` (CLI traceback, LA 500, MCP exception) and none re-reads the vault: each holds an in-memory vault from unlock time and saves it with its original revision (VAULT:407-417, 495-507). Spec 5.3 "reload, change, save under the lock, retry once" is new behaviour for all three. The lock context is private `pushkey_vault._vault_write_guard` = `_VAULT_WRITE_LOCK` (RLock) + `_cross_process_lock()` (VAULT:56-70); `save_vault` (VAULT:409), `save_vault_with_key` (VAULT:497), `replace_*` take it internally, and `write_health_sidecar` takes it again (pushkey_health.py:381, imported VAULT guard at :17), always sequentially (save returns, then publish). The cross-process part, `bounded_file_lock` (pushkey_locking.py:34-85), opens a NEW file handle per acquisition and takes a non-blocking `msvcrt.locking`/`flock` with a 5 s timeout, so by code read it is NOT re-entrant within one process (a nested `_vault_write_guard()` would wait 5 s, then `VaultBusyError`); no test covers same-process nesting (tests/test_locking.py covers a second process only) - unchecked empirically. Consequence: `pushkey_connect` cannot wrap "load + mutate + `save_vault`" in `_vault_write_guard`; the workable shape is optimistic: load a fresh `VaultData` (carries `_pushkey_revision`), mutate, `save_vault` (the revision check runs inside its lock, VAULT:413-417), on `VaultConflictError` reload and retry once, then `publish_saved_vault`. `load_config`/`save_config` are not under any lock (`save_config` writes the fixed name `config.tmp`, VAULT:571).
9. Config transaction. Only LA has `_persist_project_state` (config first, vault second, in-memory rollback). CLI `project add` writes config with no lock and no vault; CLI `project assign` writes config then vault with no rollback; MCP never writes config. Rollback of in-memory state on a failed `_save` exists only in `_persist_project_state`.
10. Scope enforcement. LA/MCP/CLI each take one scope; CLI gate is fail-open for unmapped commands and absent in the shell (scope bypass, C3); MCP has no registry so "agent adds project folders" is open via `assign_key`. `rotate` scope name appears in LA's `AgentCreate` but not in `VALID_SCOPES`.
11. Reporting shape. LA: HTTP status + JSON (`detail`), 201/204 codes; MCP: `{"success": bool, "error": str, ...}` with scope errors as `{"error": "scope_denied", ...}`; CLI: stdout text + exit codes (EXIT_USAGE=2, EXIT_AUTH=10, 1). A core returning a structured result (`written`, `reason`, per-file status, no values) can be adapted by each; inject responses today differ (`env_file` + `wrote` in LA only; counts only in MCP; `Wrote N key(s) to <path>` in CLI).
12. Audit. CLI logs a names-only `log_event` for add/rotate/delete/inject/backup; MCP logs only backup tools; LA logs nothing for key/project operations (only a UI-posted `/api/audit/log`). Spec step 6 needs one audit event from the core.
13. Plan limits. `max_projects` is defined in `pushkey_shared.TIERS` (pushkey_shared.py:34-102). Grep `within_limit|can_do(` over pushkey_cli.py, pushkey_mcp.py, pushkey_local_api.py finds only `can_do("dual_rotation")` at MCP:459, so none of CLI/MCP/LA enforces a project limit; the desktop (`pushkey.py:2641,2644,3218,5572`) does use them. LA `backup` has no `dual_rotation` tier check although MCP `set_backup_key` does (MCP:458-460), and the CLI `set-backup` has none either.
14. Where the value comes from. MCP `add_key` and LA `POST /api/keys` take the value in the call (plaintext policy, AGENTS.md); CLI `add NAME VALUE` takes it on argv; only `set-backup`, `rotate` (when the arg is omitted) and the shell prompt with getpass. The spec's "value asked with getpass when left out, as today" is true for `rotate` but not for `add` (VALUE is required, CLI:664). The MCP `add_key` warning (MCP:297-298) and AGENTS.md both tell the user to run `pushkey add NAME` with a "hidden prompt"; today that command without a value is an argparse usage error, and test_mcp.py:239 pins the substring `pushkey add NEW_KEY`. Making VALUE optional (getpass when omitted) fixes the text and the spec at once; the substring can stay.
15. Test-isolation hazards. (a) `tmp_path` is the vault dir (conftest:92-107) and tests place project folders inside it (`tmp_path/"proj"`); a core that refuses writes inside `~/.pushkey` or compares project and vault paths will break these tests. (b) `pytest.ini` sets `addopts = --basetemp=.pytest_tmp` (repo-local) and conftest nests a `s<pid>` dir under it, so test project folders sit INSIDE the Pushkey git repo; `git check-ignore -v .pytest_tmp` prints `.gitignore:14:.pytest_tmp/` (ignored). A core that runs `git rev-parse --show-toplevel` / `git check-ignore` / `git ls-files` on a test project will see the Pushkey repo (a file there reports "ignored" for the wrong reason, and "append to the root .gitignore" would target the Pushkey repo's `.gitignore`) unless the test runs `git init` in the project or the core accepts an injectable git runner. Existing tests assert a plain `project/.gitignore` is created containing `.env` (test_local_api.py:803-815, test_cli.py:470-478, test_mcp.py:366). Not run; read from pytest.ini, conftest.py and `git check-ignore`. CLI tests use a plain-dict vault with no revision (health publish fails quietly); MCP/LA tests use real `VaultData`.
16. Vault schema compatibility. `_validate_vault_schema` allows arbitrary JSON metadata (depth <= 8, lists <= 10k, dicts <= 1000 keys) and requires `projects` to be a list of strings (VAULT:144-148), so a `connections` list of `{project,file,var,added}` dicts validates. The health sidecar copies only name/status/days_old/provider (pushkey_health.py:233-235), so connections do not leak there. `_`-prefixed names are skipped by LA list/reveal/lifecycle/health routes, not by CLI/MCP (spec 5.2 already notes it).
