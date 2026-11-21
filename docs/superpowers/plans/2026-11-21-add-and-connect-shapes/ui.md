# UI mapping: desktop (pushkey.py) + web-app + bundle

Worktree: <worktree> (branch feat/add-and-connect, HEAD f48c93f).
All line numbers are this worktree. Read-only mapping; nothing edited. Anything marked "unchecked" was not probed.

## 1. pushkey.py: every use of the project store

### 1.0 Load / save / lifecycle
- Imports: `pushkey.py:98` `from pushkey_vault import load_vault, save_vault, load_config, save_config, ...`
- Login: `LoginFrame.unlock` (1900) -> `load_vault(pw)` (1920) -> `self.on_login(pw, vault, _vault_key)` (1931, or after MFA 1974) -> `PushkeyApp.on_login` (8591) -> `self.switch(AppFrame, password=pw, vault=vault, ..., vault_key=vault_key)`.
- `AppFrame.__init__` (2166): `self.vault = vault` (2169-2170), `self.config = load_config()` (2174). Both are loaded ONCE per login and never reloaded.
- `AppFrame.save()` (2371-2373), the only generic save:
  ```
  def save(self):
      save_vault_and_publish(self.vault, self.password, vault_key=getattr(self, 'vault_key', None))
      save_config(self.config)
  ```
  `save_vault_and_publish` (158-160) = `save_vault(...)` + `write_health_sidecar(vault)`.
- `load_vault` returns a `VaultData` dict carrying `_pushkey_revision` (pushkey_vault.py:42-45). `save_vault` raises `VaultConflictError("stale_vault_revision")` when the file changed on disk since load (pushkey_vault.py:407-418). `grep VaultConflictError pushkey.py` = no hits: the desktop never catches it, so a save after the CLI/web/MCP wrote the vault raises uncaught inside a Tk callback.
- `save_config(self.config)` (pushkey_vault.py:566) writes the WHOLE config dict. `self.config` also holds `theme` (2445), tray/clipboard toggles (2608-2618), `sso_settings` (3104), `cloud` (3181-3270). Desktop writes it wholesale from its stale copy (would clobber projects the web app/CLI added since login, and any `connect_schema` / `projects_legacy` written by another process).
- Saves that bypass `self.save()`: `save_vault_and_publish(self.vault, ...)` directly at 6673 (change master password) and 8282 (`_do_env_import`); `save_config(self.config)` directly at 2446 (theme), 2618 (settings toggles), 3106 (SSO), 3183/3194/3270 (cloud), 8085 (`ci_sync_project`); `_stamp_keys_used` (6368) calls `self.save()` per inject. `delete_key` (def 6414) does `del self.vault[name]` + `self.save()` and never prunes `config["projects"][*]["keys"]`.
- `load_config()` (pushkey_vault.py:541-563): missing file -> `{"projects": {}}`; decrypt with `_config_key()`; legacy plaintext JSON fallback.
- Other raw config reads that bypass `self.config` (read only `tray_on_close`, `clipboard_watcher`, `theme`): 8323-8330, 8395-8402, 8476-8483 (`raw.lstrip()[:1] == b"{"` then json.loads; effectively reads defaults because the file is encrypted).
- Where a once-per-unlock `pushkey_connect.migrate()` could hook for desktop: between `load_vault` (1920 / 2157) and `AppFrame.__init__` 2174, or at the top of `AppFrame.__init__`.

### 1.1 Reads/writes of `config["projects"]` (all name-keyed today; each uses the old shape `{path, keys, target_env, added, ci_*}`)
| file:line | function | what it does |
|---|---|---|
| 3757-3759 | `import_vault` | merges backup's `config["projects"]` entries by NAME if name not present: `for proj, info in imported_config.get("projects", {}).items(): ... self.config.setdefault("projects", {})[proj] = info`. Also `self.vault.update(imported_vault)` (3756) replaces whole key entries (drops local `projects`/`connections`). `export_vault` (3733) dumps `{"vault": self.vault, "config": self.config}`. |
| 3924-3927 | key lifecycle card | `proj_count = sum(1 for p in self.config.get("projects", {}).values() if name in (p.get("keys") or []))`. Shown at 4047-4049. In the new store entries have no `keys`, so this goes to 0 unless switched to `vault[name]["projects"]`. |
| 4630 | dashboard | `projects = len(self.config.get("projects", {}))` (stat card at 4713). |
| 6334-6347 | `_auto_inject_keys_bulk` | loop over projects; `relevant_keys = [k for k in key_names if k in proj_keys or not proj_keys]`; `path = proj_info.get("path")`; `inject_env_file(path, self.vault, proj_keys if proj_keys else None, target_env=proj_info.get("target_env","all"))`. Empty list = every key. |
| 6352-6366 | `_auto_inject_key` | same loop; `if key_name in proj_keys or not proj_keys:` -> `keys_to_write = proj_keys if proj_keys else None`. Skips entries without `path` (6356). |
| 7134-7136 | `_run_scan` | `scan_roots = {info["path"] for info in projects.values() if info.get("path") and os.path.isdir(info["path"])}` |
| 7186-7187 | git-history scan | same `scan_roots` expression. In the shared store the path is the DICT KEY and entries have no `path`, so both scans silently scan nothing. |
| 7686-7695 | `render_projects` | `projects = self.config.get("projects", {})`; empty -> "No projects linked yet." text (7688); `for proj_name, proj_info in sorted(projects.items()): self._draw_project_card(pad, proj_name, proj_info)`. |
| 7706-7725 | `_draw_project_card` (def 7697) | reads `proj_info.get("keys", [])`(7706), `_auto_match_keys(proj_name)`(7707), `.get("path","")`(7710), `.get("added")`(7711; shared store uses `created`), `.get("target_env","all")`(7712), `path_obj / ".env"` (7725 only `.env`). Status pill: `has_keys` ACTIVE / `partial` NEEDS ASSIGN / EMPTY (7708-7720). Card title is `proj_name` (the dict key; would show an absolute path in the new store). Buttons (7817-7830): "Sync .env" -> `sync_project`, "CI Sync" -> `ci_sync_project`, "Assign Keys" -> `assign_keys_to_project`, "Remove" -> `remove_project`. |
| 7859-7860 | `add_project` | `proj_count = len(self.config.get("projects", {}))`; `if not self._gate("max_projects", proj_count): return` (gate impl 2634-2690: `within_limit(feature, current_count)`). |
| 7863-7875 | `add_project` | `self.config["projects"][name] = {"path": path, "keys": matched, "added": datetime.now().isoformat(), "target_env": target_env}`; `matched = self._auto_match_keys(name)` (7867) = name-prefix auto-assign; then `inject_env_file(path, self.vault, target_env=target_env)` (7876: writes EVERY env-matching key, ignoring `matched`); `self.save()`. Key is the user-typed name; path not canonicalised; duplicates by name only. |
| 7886-7896 | `_refresh_project_keys` | `matched = set(self._auto_match_keys(proj_name))`; `proj["keys"] = sorted(current | matched)`; `self.save()` -- silent prefix auto-assign on every key import. Called by `_refresh_all_projects` (7898-7900) from import flows at 6087, 6176, 6262 and from `sync_project`. |
| 7902-7999 | `sync_project` (confirm dialog) | `proj = self.config["projects"].get(proj_name)` (7903); `path = proj["path"]` (7907); `assigned = set(proj.get("keys", []))` (7913); `keys_to_write = sorted(k for k in assigned if k in self.vault)` (7914); reads existing `.env` via `_parse_env_line` to classify rotate/new/unchanged (7928-7945); `confirm()` -> `inject_env_file(path, self.vault, keys_to_write if keys_to_write else None, target_env=proj.get("target_env","all"))` (7990-7991: EMPTY assigned list = write all vault keys) then `_stamp_keys_used`. Existing preview/confirm UI is a good reusable pattern (mask(), before->after rows). |
| 8001-8122 | `ci_sync_project` | `proj = self.config["projects"].get(proj_name, {})` (8004); `assigned = set(proj.get("keys", []))`; `keys_to_sync` (8005-8006); persists CI fields straight on the project dict: `proj[k] = v` (8083) for non-token fields (github_owner, github_repo, vercel_project_id, vercel_target, railway_project_id, railway_env_id) and `proj["ci_platform"] = plat` (8084), then `save_config(self.config)` (8085). These extra desktop-only fields are NOT in the spec's `{name, created, default_file, environment}`. |
| 8124-8127 | `_auto_match_keys` | `prefix = re.sub(r"[^A-Z0-9]", "_", proj_name.upper())` ...; `return [k for k in self.vault if k == prefix or k.startswith(prefix + "_")]` -- PREFIX FROM PROJECT NAME; in the new store the dict key is a path so the prefix would be garbage unless `name` is passed. |
| 8129-8180 | `assign_keys_to_project` | window 420x480 (8137); `current_keys = set(self.config["projects"][proj_name].get("keys", []))` (8146); pre-check rule `checked = key_name in current_keys or (not current_keys and key_name in matched)` (8161: empty list -> pre-tick prefix matches); `save_assignment()` (8173-8178): `self.config["projects"][proj_name]["keys"] = selected; self.save(); win.destroy(); self.render_projects()`. Writes NOTHING to the vault today. |
| 8182-8186 | `remove_project` | `del self.config["projects"][proj_name]; self.save(); self.render_projects()`. Does not clean `vault[*]["projects"]` (the web API's delete does, pushkey_local_api.py:917-923). |
| 8651 | `_cli_main` "inject" | headless: `inject_env_file(path, vault, key_names=ns.keys, target_env=ns.env)`. Never reads config. `--keys` with nargs="*" and empty -> all keys. `rotate` (8688-8699) updates the vault but does NOT inject. Reached from `main()` (8710-8716) when `sys.argv` has args. |

Other triggers of inject (use `_auto_inject_*`, no direct config reads):
- 5563-5565 `_inline_inject` (expand-panel button "->  Inject .env", 5529) -> `_auto_inject_key(name)`.
- 5887 `add_key` after `self.save()`; 6263 bulk upload (`_auto_inject_keys_bulk`); 6435 `_apply_rotation`.
- `_promote_backup_key` (5631-5660) promotes the backup and calls `self.save()` but never injects (spec: promote must trigger sync).
- `inject_env_file` itself (1126-1148; `if key_names:` branch at 1133-1136): `_env_match(key_env)`; `if key_names: names = [k for k in key_names if k in vault and _env_match(...)] else: names = [all env-matching keys]`; calls `pushkey_env.mutate_env_file(project_path, vault, key_names=names, update_existing=True, backup_existing=True)`. `mutate_env_file` (pushkey_env.py:66) writes only `<project>/.env`; `selected_names = key_names or list(vault_entries.keys())` (pushkey_env.py:80: empty list also means all); backup name `.env.pushkey_backup_<ts>` (pushkey_env.py:112-114 region); var name == vault key name. `_stamp_keys_used` (6368-6377) writes `first_used`/`last_used` into the vault and saves.
- pushkey.py also has a local `_ensure_gitignore_env` (1109) that only matches the exact line `.env` (only defined here; `pushkey_env.ensure_gitignore_env` is the one `mutate_env_file` uses).

### 1.2 Reads/writes of `vault[KEY]["projects"]`
- READ 5412-5413 (`_render_expand_panel`): `raw_projs = info.get("projects", [])`; `projects = [p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in raw_projs]`; rendered as pills at 5488-5499 (`for proj in projects[:6]`). With the shared store this would show full absolute paths, capped at 6.
- WRITE 8275 (`_do_env_import`, 8213): new env-imported keys get `"projects": []`, `"env": "production"` (not in `ENV_LEVELS`), `"notes"`, `"source": "env_import"`. Also uses `prov_info.get("name")` on a `detect_provider` return that is a plain `str`/`None` (pushkey_providers.py:85-95), a latent bug.
- No other desktop writer sets `projects`. `add_key` (new-key branch 5878-5883) builds `{"value","category","provider","created","rotated":None,"rotation_count":0,"previous":None,"env"}` with no `projects`/`connections`. Group-add (6076), scan-import (6167) and bulk-upload (6252) entries also omit it.
- Vault schema check (pushkey_vault.py:124-176): `projects` must be a `list[str]` (non-str items raise `invalid_projects`, so the dict tolerance in 5413 is dead code); `connections` as list of dicts of strings passes `validate_value` (depth <= 8, lists <= 10_000, dicts <= 1_000 fields). `_`-prefixed vault names are tolerated by the schema check and skipped by the desktop in key counts (2312, 3819, 4195, 4625, 5859) but not everywhere.
- Real shared-store producers for the shape: web `POST /api/projects` writes `current_cfg["projects"][canonical] = {"name": body.name or Path(canonical).name, "created": _now_date()}` (pushkey_local_api.py:902-905; `created` is `%Y-%m-%d`, desktop `added` is a full isoformat); `assign` appends the canonical path to `vault[key]["projects"]` (938-940); web `list_projects` returns `{path, name, keys (computed from vault[*].projects), created}` (880-891).
- A desktop name-keyed entry today shows up in the web list as path="myapp", name = `meta.get("name", ...)` fallback = "myapp", `keys: []` (no vault allowlist), because `_canonicalize_registered_projects` (pushkey_local_api.py:369-397) leaves non-absolute keys alone.

## 2. pushkey.py: add-key window and key view

### 2.1 Add-key modal: `_show_add_key_modal` (5775-5845), `add_key` (5847-5890)
Style (copy exactly; no `ttk`, everything CTk):
```
win = ctk.CTkToplevel(self); win.title("New Key"); win.geometry("520x360")   # 5776-5778 (fixed height, will need to grow)
win.configure(fg_color=C["bg2"]); win.transient(self); win.grab_set(); win.lift()
ctk.CTkLabel(win, text="Add New Key", font=FONT_H2, text_color=C["text"]).pack(anchor="w", padx=24, pady=(20, 16))
def field(parent, label, widget_fn):          # 5787-5792 local helper: frame + FONT_XS C["text3"] caption + widget
    f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=24, pady=(0, 10)) ...
self.add_name  = field(win, "KEY NAME", lambda p: ctk.CTkEntry(p, font=FONT_MONO_SM, fg_color=C["bg3"], text_color=C["text"], border_color=C["border2"], placeholder_text="OPENAI_API_KEY"))
self.add_value = ... show="●"
self.add_cat   = ctk.CTkOptionMenu(cf, values=[...], fg_color=C["bg3"], button_color=C["bg4"], button_hover_color=C["btn_hover"], text_color=C["text"], font=FONT_XS)   # 5813
self.add_env   = ctk.CTkOptionMenu(ef, values=ENV_LEVELS, ...)  # 5826, default "all"
make_btn(btn_row, "Add Key", lambda: (self.add_key(), win.destroy()), fg_color=C["accent"], text_color=C["bg"], height=36)   # 5836
make_btn(btn_row, "Cancel", win.destroy, fg_color=C["btn"], text_color=C["text2"], height=36)
self.add_value.bind("<Return>", lambda e: (self.add_key(), win.destroy()))   # 5845
```
- Inputs are stored as instance attrs `self.add_name/add_value/add_cat/add_env`, read by `add_key`; `add_cat` is also probed by bulk import via `hasattr(self, "add_cat")` (6252).
- `make_btn(parent, text, command, fg_color=None, text_color=None, width=None, height=32, corner_radius=6, anchor=None, border=True)` at 1315-1337 (always 1px `C["border"]` border unless `border=False`). Fonts: `FONT_XS` (UI 11), `FONT_MONO_SM`, `FONT_H2`, `FONT_BTN` (1249-1257). Colors `C[...]` palette (C_DARK/C_LIGHT 1151-1245 region): bg/bg2/bg3/bg4, surface, accent, text/text2/text3, border/border2, green/amber/red + `*_bg`.
- GOTCHAS: (a) both the button and `<Return>` run `self.add_key(), win.destroy()` so the window closes even when `add_key` returns early (missing info 5854, tier gate 5860-5861, user answers No to the "Rotate key?" prompt 5867-5868). A connect section needs `add_key` to return success/failure or the window to be closed only on success. (b) `add_key` (5847): name upper-cased and spaces to `_` (5848); gate `max_keys` only for new names (5858-5861); existing name -> askyesno then rotate in place inline (5869-5877; not via `_apply_rotation`, which is at 6423-6442); then `self.save()` (5886), `self._auto_inject_key(name)` (5887) which is the old auto-write to all/empty-list projects, then `messagebox.showinfo("Done", msg)`. (c) provider = `detect_provider(name, value)` string/None. (d) `_show_add_key_modal` callers: 4991 (empty dashboard), 5054 (+ New Key), 8469 and 8560 (tray/menu via `self.frame`).

### 2.2 Key view: there IS an inline per-key detail panel (no separate modal/window)
- Rows: `render_keys` (5036) builds header + search + `self.keys_scroll`; `_render_key_rows` (5143) re-renders ALL rows by destroying every child (5145-5146) then, per group, `self._render_single_key(name, info)` (def 5238) and, if `name == self._expanded_key`, `self._render_expand_panel(name, info)` (5211-5212).
- Row click = `_toggle_expand(name)` (5229): sets `self._expanded_key`, clears `_rotate_pending/_rotate_result`, re-renders.
- `_render_expand_panel(name, info)` (5402-5561) = the key detail. Layout: 3px category-colour outer frame -> `inner_bg` -> `body` with LEFT pane (VALUE box with Show/Hide 5447-5467, 2x2 meta grid PROVIDER/ENV/CREATED/ROTATED via `_meta_cell` 5469-5486, then the "PROJECTS" pill block 5488-5499), a 1px divider (5501-5503), RIGHT pane 150px wide with "ACTIONS" (5510): Copy Value, Rotate, "->  Inject .env" (5529), dual-rotation buttons (5533-5553), "Revoke" (5555-5558), and the inline rotate sub-panel (5560-5561, `_render_rotate_subpanel` def 5672).
- Best insertion point for a "Used in" list: replace/extend the PROJECTS pills block at 5488-5499 (left pane, `pack(anchor="w")` with `ctk.CTkLabel(left, text="PROJECTS", font=(_UI_FONT, 9, "bold"), text_color=C["text3"])`). Status pills should reuse the Health/Env pill style (`CTkFrame(fg_color=tinted_bg, corner_radius=8, border_width=1, border_color=fg)` + label `(_UI_FONT, 8, "bold")`) from `_render_single_key` 5355-5395. "Update now" / "Disconnect" go into the same left pane as `make_btn(..., height=22/28, border=False)` or into the right pane list.
- Wipe-and-rebuild means any new widget state must live on `self` (like `self._expanded_key`) not in locals.

## 3. Desktop tests (no display)

- No test builds a real `ctk`/`tk` root or `AppFrame`. `import pushkey` works headless (module top level creates no root; `tests/test_ui_helpers.py:3`, `test_env_injection.py:3`, `test_cloud_client_sync.py:18`).
- Only headless GUI pattern: call the unbound `AppFrame`/`PushkeyApp` method on a hand-made fake, `tests/test_ui_helpers.py:122-136`:
  ```
  class FakeApp:
      _expanded_key = None; _rotate_pending = False; _rotate_result = None; _render_called = False
      def _render_key_rows(self): self._render_called = True
  app = FakeApp()
  app._toggle_expand = types.MethodType(pushkey.AppFrame._toggle_expand, app)
  app._toggle_expand("OPENAI_API_KEY")
  ```
  (also 140-170; and 83-119 for `PushkeyApp._cancel_active_health_refresh(app)` / `_quit_from_tray` with `type("App", (), {...})()` stubs). Module-level collaborators are swapped with `monkeypatch.setattr(pushkey, "log_event", ...)`, `monkeypatch.setattr(pushkey, "publish_saved_vault", ...)` (45-78). `messagebox` is a module-level import (pushkey.py:20), so `monkeypatch.setattr(pushkey, "messagebox", fake)` works for methods that show dialogs.
- Project logic tests: `tests/test_multi_project.py` (122 lines) does NOT touch desktop logic. It writes name-keyed configs `{"projects": {"project1": {"path": ..., "keys": [...]}}}` through `pushkey_shared.CONFIG_FILE.write_text(json.dumps(config))` (26-45) or `monkeypatch.setattr(pushkey, "CONFIG_FILE", ...)` (55, 80) and round-trips `pushkey.load_config()/save_config()` (78-96). Pure config JSON round-trip; they only break if `load_config()` itself starts reshaping data (put migration in `pushkey_connect.migrate()`, not in `load_config`). `pushkey.CONFIG_FILE` must keep existing (monkeypatch default raising=True; imported at pushkey.py:76).
- `tests/test_env_injection.py` (50 lines): 3 tests call `pushkey.inject_env_file(tmp_path, vault[, key_names=["B"]])` directly: merge/quote values, no duplicate `.gitignore` line (exact `.env` line count == 1), key filter. They pin the existing `inject_env_file` signature and the `# Managed by Pushkey` marker.
- No test covers `_auto_inject_key`, `add_project`, `sync_project`, `assign_keys_to_project`, `_auto_match_keys`, `render_projects`, `_run_scan`. (`grep -rln '_run_scan\|remove_project\|_auto_inject\|add_project\|sync_project\|assign_keys_to_project\|_auto_match_keys\|render_projects' tests/*.py` hits only `tests/test_local_api.py`, and that hit is `test_assign_keys_to_project` at line 742, a web-API test, not desktop.) `tests/test_key_rotation.py`, `test_vault_crypto.py`, `test_encryption_edge_cases.py` use vault functions only.
- Isolation: `tests/conftest.py:92-107` autouse `isolate_vault_paths` monkeypatches every `pushkey_shared` path under `~/.pushkey` to `tmp_path`, so `load_config()/save_config()/load_vault()` are safe in new tests; do not patch `pushkey.*` path attrs.
- `tests/test_url_scheme_guard.py:24` scans pushkey.py/pushkey_cli.py/pushkey_providers.py/pushkey_tiers.py source for direct `urllib.request.urlopen(` (must use `pushkey_shared.urlopen_checked`); relevant only if new code does HTTP.
- Caller labels for `_show_add_key_modal` (4991 empty-state button, 5054 header button, 8469/8560 tray/menu paths via `self.frame`) were taken from grep lines, not read in context (unchecked).
- Recommended testable shape (inference, not existing): keep logic in `pushkey_connect` (pure, tmp_path), keep desktop methods thin, test them with the FakeApp + `types.MethodType` pattern above and a fake `messagebox`.

## 4. web-app

### 4.1 Layout (no vitest/jest; only Playwright e2e)
```
web-app/package.json  scripts: dev "next dev -p 4173", build "next build && node scripts/generate-integrity.mjs",
                      integrity "node scripts/generate-integrity.mjs", start, lint "eslint", test:e2e "playwright test"
web-app/src/app/{layout,page}.tsx  (page.tsx:140-141 renders {tab==="vault" && <VaultTab/>}, {tab==="projects" && <ProjectsTab/>})
web-app/src/components/{vault-tab(681 lines),projects-tab(481),lifecycle-tab(232),dashboard-tab,health-tab,forecast-tab,agents-tab,audit-tab,settings-tab,sidebar,login-screen}.tsx
web-app/src/components/ui/{badge,button,card,input,label,table}.tsx
web-app/src/lib/{api.ts(223),auth.ts,toast.tsx,utils.ts}
web-app/tests/e2e/{accessibility,wcag,smoke,local-vault}.spec.ts + support/mock-local-api.ts
```
Stack: Next 16 static export (`next.config.ts`: `output: "export"`, `trailingSlash`), React 19, Tailwind 4, radix, lucide-react. `node_modules/` is NOT installed in this worktree (needs `npm ci`; Node v24.12.0 + npm on PATH).

### 4.2 `web-app/src/lib/api.ts` (client = object `api`, all via `request<T>(path, {method?, body?, query?})`, bearer token from sessionStorage)
Types (api.ts: KeySummary 64, KeyDetail 77, Project 86):
```
export type KeySummary = { name; env; rotated: string|null; added: string|null; provider: string|null; dual_rotation: boolean; has_backup: boolean; history_count: number; team_role: string|null; masked: string };
export type KeyDetail = KeySummary & { value: string; next_value: string|null; next_added: string|null; history: {value;retired}[]; projects: string[]; notes: string };
export type Project = { path: string; name: string; keys: string[]; created: string | null };
export type LifecycleResp = {... history; projects: string[]};   // lifecycle projects = raw vault[key].projects
```
Functions (`export const api = {` at 153; listKeys 161, addKey 163, listProjects 177, assignKeys 182, injectProject 186):
```
listKeys:  () => request<{keys: KeySummary[]; count}>("/api/keys")
revealKey: (name) => request<KeyDetail>(`/api/keys/${encodeURIComponent(name)}`)
addKey:    (body:{name; value; provider?; env?; notes?}) => request<KeySummary>("/api/keys", {body})   // server returns {name, provider, env}
updateKey / deleteKey / rotateKey(name,new_value) / setBackup / promote
listProjects:  () => request<{projects: Project[]; count}>("/api/projects")
createProject: (path, name?) => request<{path; name}>("/api/projects", {body:{path,name}})
deleteProject: (path) => request<void>(`/api/projects?path=${encodeURIComponent(path)}`, {method:"DELETE"})
assignKeys:    (path, keys[]) => request<{path; assigned: string[]}>(`/api/projects/assign?path=...`, {body:{keys}})
unassignKeys:  (path, keys[]) => ...`/api/projects/unassign?path=...`
injectProject: (path, preview?) => request<{injected; skipped_existing; env_file; wrote}>(`/api/projects/inject?path=...&write=${!preview}`, {body:{}})
```
No type for connections exists yet; `KeySummary` has no `projects` field (list route `GET /api/keys` returns none; only `GET /api/keys/{name}` and `/api/lifecycle/{name}` expose `projects`).

### 4.3 Components that need the new screens
- Add-key form: `components/vault-tab.tsx`. State `showAdd/addForm/addLoading` (62-64), `EMPTY_ADD = { name:"", value:"", provider:"", env:"dev" }` (46), `handleAdd` (152-176) calls `api.addKey({...})` then `refresh()` and `toast.success("Key added")`. Form JSX 564-630: `<form id={addFormId} onSubmit={handleAdd}>` with `grid grid-cols-2 gap-3`, `Label`+`Input` pairs (`id="add-name"`, `add-value` type=password, `add-provider`, native `<select id="add-env">` over `ENV_OPTIONS = ["dev","staging","prod","all"]`), submit `Button type="submit" size="sm"` "Add key". Toggle button 514-524 (`aria-expanded={showAdd}`, text "Add key"/"Cancel").
- Key detail / "Used in": there is NO per-key detail component in the web app. The vault table has one `renderRow(k: KeySummary)` (285) returning a `Fragment` of `TableRow` + optional inline rows (rotate 383, backup ~410, edit ~445) that use `colSpan={7}` and per-key state maps (`rotateState/backupState/editState`, `closeAllFor` 190-194, `focusToggleFor`). A "Used in" panel fits as a fourth inline row with its own `aria-expanded`/`aria-controls` toggle button (follow the `editRowId` pattern, a11y tests grep these strings). The only existing per-key detail view is the lifecycle tab (`lifecycle-tab.tsx:213-226`, "Assigned Projects" list of `detail.projects`, bare path strings).
- Project side: `components/projects-tab.tsx`. `ProjectPanel` (58) calls `api.injectProject(project.path, false)` (84, button "Inject .env", `aria-label={`Inject environment file for ...`}`), `api.assignKeys` (98), `api.unassignKeys` (111); `InjectResult` (29) shows `injected` / `skipped_existing` ("Conflict: existing values kept for ..."); `ProjectCard` (206) delete via `api.deleteProject` (228); `AddProjectForm` (329) -> `api.createProject` (343); `ProjectsTab` (411) loads `Promise.all([api.listProjects(), api.listKeys()])` (421). Cards are keyed by `project.path` and display `project.name || project.path`.
- Components that call key/project api functions (grep `api\.(listKeys|addKey|listProjects|revealKey|assignKeys|injectProject)` in web-app/src): `vault-tab.tsx`, `projects-tab.tsx`, `lifecycle-tab.tsx`, `dashboard-tab.tsx` (only these four).
- Backend routes the UI hits (pushkey_local_api.py): `GET/POST /api/keys` 648/776 (`KeyCreate` model 85-91 is a `StrictBody`: unknown fields rejected, so a `connect` object needs a model change; `env: Literal["dev","test","staging","prod","all"]`), `/api/projects*` 863-1010 (`ProjectCreate` 108, `ProjectAssign` 113, `InjectBody` 117, `_canonical_project_path` 290, `_atomic_project_write` 334, `_persist_project_state` 734, `_canonicalize_registered_projects` 369). Inject today: `update_existing=False` (skips existing values, 1011) and only `.env`.

### 4.4 Test setup for web-app
- Playwright only (`playwright.config.ts`: chromium/firefox/webkit, baseURL http://127.0.0.1:4173, webServer `npm run dev`). No unit-test runner in package.json.
- `tests/e2e/support/mock-local-api.ts` (`installRoutes(page, locked, options)`): `page.route("**/api/...")` stubs for bootstrap, status, health, forecast, keys (`{keys: [], count: 0}`, line 85), projects (`{projects: [], count: 0}`, 92), agents, audit, lock. Any new endpoint called on screen load/open (suggestions, connections list) must be stubbed here or the axe scans see error banners.
- `tests/e2e/wcag.spec.ts` (run in CI): scans "vault list" (73), "add-key form" (82-89: clicks "Open Vault" then "Add key" then axe), "projects" (101). A new "Connect to project" section inside the add-key form is inside an existing axe scan. `accessibility.spec.ts` asserts named controls.
- `tests/e2e/local-vault.spec.ts` is a full journey against a real Python server (hard-coded `.venv/Scripts/python.exe`, Windows path, line 7) that creates a project, assigns, injects (lines 134-147).
- CI job `local-web-app` (.github/workflows/ci.yml:74-118; Node 24): `npm ci`, `npm run lint`, `npm run build`, `npx playwright install --with-deps chromium`, then `npm run test:e2e -- accessibility.spec.ts wcag.spec.ts --project=chromium`. Release workflow (release.yml:95-101) does `npm --prefix web-app ci`. No workflow compares the committed bundle with a rebuild (`grep -rn 'pushkey_web\|_manifest\|git diff' .github/workflows` = no hits).
- Python-side static tests that read web-app SOURCE text (they must keep passing after UI edits):
  - `tests/test_local_contracts.py:24-41,60-67`: every `request(...)` path string in api.ts (regex `request(?:<[^>]+>)?\(\s*(["`])(.+?)\1`, query string stripped, `${encodeURIComponent(x)}` -> `{x}`) must be a literal route in `pushkey_local_api.py` decorators AND appear verbatim in `docs/local-api-v1.md` (table rows like `| POST | `/api/projects/assign` | ... |`, lines 34-47). Param names must match the route's (`{name}`).
  - `tests/test_local_api_contract_static.py:14-56`: same idea with a second regex (`request<[^>]+>\(` + backtick/quote + `/api/...`): generic type args containing `>` (e.g. `Array<X>`) would defeat `[^>]+`, so use named types.
  - `tests/test_web_app_security.py:11-35`: vault-tab keeps `REVEAL_TIMEOUT_MS = 10_000`, `CLIPBOARD_CLEAR_TIMEOUT_MS = 30_000`, `navigator.clipboard.writeText("")`; no `localStorage`/`console.log` anywhere in src; `sessionStorage` only in `lib/auth.ts`.
  - `tests/test_web_app_states.py:15-37`: strings "Vault is empty." (vault-tab), "No projects registered." (projects-tab), `ErrorBanner` in projects-tab, "conflict" in projects-tab, etc.
  - `tests/test_web_app_accessibility_static.py:11-91`: required aria strings in vault-tab/projects-tab (`aria-expanded={expanded}`, `aria-controls={panelId}`, `role="region"`, `aria-label={`Unassign `...`, `aria-label={`Assign `...`, `aria-label={`Delete project `..., `aria-label={`Inject environment file for `..., `aria-pressed={!!revealed[k.name]}`, `aria-expanded={rotateState[k.name] !== undefined}`, `aria-label={`New value for ${k.name}`}` etc.). Renaming/removing any of those strings fails Python tests. `tests/test_web_analytics_consent.py:25-34` asserts no `localStorage`, `gtag`, `posthog`, `plausible` in web-app/src (read).

## 5. The bundle

- Source -> bundle in ONE command, run from `web-app/`: `npm ci` (first time) then `npm run build` = `next build && node scripts/generate-integrity.mjs`. `generate-integrity.mjs` (the whole pipeline):
  1. walks `web-app/out/`, sha256 of every file -> `files{}`; collects CSP hashes of every inline `<script>`, `<style>` and `style="..."` attribute in `.html` -> `csp{scripts,styles,style_attributes}`;
  2. writes `web-app/out/pushkey-integrity.json` (`{schema:1, web_app_version, files, csp}`), chmod 0444;
  3. `rm -rf ../pushkey_web/out` and `cp -r out ../pushkey_web/out`;
  4. rewrites `pushkey_web/_manifest.py` (trust anchor, "Do not edit"):
     ```
     EXPECTED_MANIFEST_SHA256 = "95cb49fb0d305724d96e9865d350774e623a68d42e3b52e5e04365d22af6cf1f"
     WEB_APP_VERSION = "0.1.0"
     ```
     (value = sha256 of the manifest file bytes; I recomputed the current `pushkey_web/out/pushkey-integrity.json` and it equals this value; 30 files, 11 script / 1 style / 4 style-attribute CSP hashes.)
- `build_exe.py` ALSO rebuilds it: `build()` (build_exe.py:132-140) runs `subprocess.run(["npm","run","build"], cwd=root/"web-app")` before `build_gui`/`build_cli`, i.e. every exe build (GUI or `--cli-only`, also the release workflow) rewrites `web-app/out`, `pushkey_web/out/**` and `pushkey_web/_manifest.py` in the working tree. `build_cli` (123-126) then bundles `web-app/out` via `--add-data` and refuses to run if `web-app/out/pushkey-integrity.json` is missing.
- Both `pushkey_web/out/**` (33 tracked files incl. `_next/static/<buildId>/...`) and `pushkey_web/_manifest.py` are COMMITTED (`git ls-files pushkey_web`); `web-app/out` and `.next` are gitignored and absent here. Precedent commits: `0f69f3d build: refresh the bundled web app`, `0686220` (touches `_manifest.py` + ~25 bundle files). No `generateBuildId` is configured, so every build changes the build id directory, chunk names and the manifest hash: expect a full-bundle diff on every rebuild.
- Runtime check: `pushkey_local_api.py:1302-1304` runs `_verify_static_manifest(static)` inside `create_app()`, and `app = create_app()` runs at import (1333). It fails closed (`RuntimeError("bundled web app integrity verification failed")`) unless (a) sha256 of `pushkey-integrity.json` == `EXPECTED_MANIFEST_SHA256` (pushkey_local_api.py:73 import, 261-286), (b) `web_app_version == WEB_APP_VERSION`, (c) file inventory == `files` keys exactly, (d) every file digest matches. CSP header is built from the manifest hashes (1305-1311), so inline styles/scripts not present at build time are blocked (existing code already uses `style={{...}}`, e.g. forecast-tab.tsx:64,79,92, which is why 4 `style_attributes` hashes exist; a new prerendered inline style adds a hash after rebuild, runtime-only inline styles are untested/unchecked).
- `_static_dir()` (pushkey_local_api.py:242-258) prefers `web-app/out`, then `_MEIPASS/web-app/out`, then `pushkey_web/out`, then importlib resources. If someone leaves a stale local `web-app/out` it wins over the committed bundle (but must still match the anchor).
- Python tests that exercise the bundle: `tests/test_local_api.py` (`test_security_headers_present` 307, `test_static_manifest_rejects_tampered_asset` 316, `test_manifest_covers_every_static_asset` 330, and every test using the `fresh_app` fixture, which re-imports `pushkey_local_api` and therefore verifies the bundle at import: lines 21-27). Also anything importing `pushkey_local_api` at module level. `pushkey_cli` only imports it lazily inside a function (`from pushkey_local_api import run_server`, pushkey_cli.py:648) and checks the file exists (842-844), so CLI-only tests do not trip the anchor unless they start the server. `tests/test_public_export.py:77-88` only checks export excludes `web-app/out`.
- What a web-app source change needs before pytest is green:
  1. Source-only edit with NO rebuild: bundle and anchor are untouched and self-consistent, so `test_local_api` manifest tests still pass; only the source-text tests in 4.4 can fail. (The UI shipped would still be the old bundle.)
  2. To ship the new UI: run `npm run build` in `web-app/` (do not hand-copy `out/`; hand-built output without the script leaves the anchor stale and EVERY test that imports `pushkey_local_api` fails at import). Commit `pushkey_web/out/**` + `pushkey_web/_manifest.py` together with the source.
  3. Python side for new routes: backend routes + `docs/local-api-v1.md` table rows + `api.ts` must agree (4.4), or `test_local_contracts.py` / `test_local_api_contract_static.py` fail.
  4. `npm run lint` and the two axe specs run in CI against the mocked API (extend `mock-local-api.ts`).
- Packaging tests triggered by a NEW module `pushkey_connect.py` (shared by desktop/CLI/web/MCP): `tests/test_package_metadata.py` asserts (a) every `pushkey_*` module imported by `pushkey_cli.py` is in `pyproject.toml` `py-modules` (line 52), and (b) `packaged - SUBMODULES == {"pushkey_cli"}`, i.e. the module must be in BOTH `pyproject.toml` `py-modules` and `build_exe.py` `SUBMODULES` (list at build_exe.py:10-23). Also add to `Pushkey.spec:6` hiddenimports (not tested) and optionally `scripts/public_export.py:14-44` allowlist (already missing `pushkey_health`/`pushkey_locking`/`pushkey_web`, so not enforced). `tests/test_packaging.py:7` has its own small `REQUIRED_MODULES` list.

## 6. Risks for the migration (each from a probe above)

1. Name-keyed assumptions: every desktop reader treats the config key as a NAME and the value as `{path, keys, target_env, added}` (6334, 6352, 7134, 7186, 7686-7712, 7868, 7903-7913, 8004, 8146, 8175, 8184). `_draw_project_card` titles with the dict key, `_auto_match_keys(proj_name)` prefixes from it, scans/inject use `info["path"]`/`proj["path"]`. In the path-keyed store `path` is the key and absent from the value; naive reuse silently disables the secret scans (7135, 7187) and crashes `sync_project` (`proj["path"]` KeyError, 7907).
2. "Empty list = every key" is in five desktop places plus the writer: 6336 (`or not proj_keys`), 6354, 7990 (`keys_to_write if keys_to_write else None`), 1133-1136 (`inject_env_file` with falsy `key_names` writes all), pushkey_env.py:80 (`key_names or list(vault_entries)`), and the UI pre-tick at 8161. A connection-driven writer must never pass an empty list through `inject_env_file`.
3. Name-prefix auto-assign (the silent rule the spec removes) lives in `add_project` 7867, `_refresh_project_keys` 7890-7893 (run from every import flow 6087/6176/6262 and from `sync_project`), `_auto_match_keys` 8124, and the assign dialog 8161. All four need removal/replacement with suggestions.
4. Stale in-memory state: `self.vault` / `self.config` loaded once (2169-2174); `self.save()` rewrites both wholesale (2371-2373) and the desktop never catches `VaultConflictError` (no grep hit). Migration or any `pushkey_connect` write by another process makes the desktop's next `save()` raise or overwrite (config has no revision check at all; `save_config` last-writer-wins). After `pushkey_connect` writes, the desktop must reload `self.vault`/`self.config`; `config` also carries theme/cloud/sso settings the desktop must keep.
5. Desktop-only project fields are lost in the new schema: `ci_platform`, `github_owner`, `github_repo`, `vercel_project_id`, `vercel_target`, `railway_project_id`, `railway_env_id` (8083-8084), `target_env` ("all" is a valid desktop value; spec `environment` default "dev", env label list `["all","dev","staging","prod"]` at pushkey_shared.py:133 vs web `Literal` adding "test"), `added` (isoformat) vs `created` (`%Y-%m-%d`, pushkey_local_api.py:906/_now_date). Migration must carry or consciously drop them; `_parse_iso` (1340) handles both date forms.
6. `vault[*]["projects"]` must be `list[str]` (pushkey_vault.py:137-141 raises `invalid_projects` otherwise); the expand panel (5412-5413) renders `str(p)` = absolute path, truncated to 6 (5494); the lifecycle card counts projects via `config[...]["keys"]` (3924-3927) and will show 0.
7. Backup import (3737-3761) merges old name-keyed `config["projects"]` entries and `vault.update(imported_vault)` (3756) replaces whole key entries, dropping local `projects`/`connections`; the exported config (3733) includes `projects_legacy` and `connect_schema` markers after migration and re-introduces name-keyed entries from old backups.
8. Existing desktop tests/hooks that pin the old shape: `tests/test_multi_project.py` (data-only, safe unless `load_config` changes) and `tests/test_env_injection.py` (pins `inject_env_file` signature/behaviour); no tests protect the desktop project flows, so new desktop code has no regression net unless tests are added with the FakeApp pattern.
9. Add-key window closes unconditionally (5836, 5845) even when `add_key` bails; `add_key` duplicates rotate logic inline (5869-5877) rather than `_apply_rotation` (6423-6442) and never sets `projects`/`connections`; both inject only through the old `_auto_inject_key` (5887, 6435). `_promote_backup_key` (5631) and `_cli_main rotate` (8680-8700) never inject.
10. Window geometry fixed at `520x360` (5778) and keys list fully re-rendered on every change (5145): the connect section needs a taller window and state on `self`.
11. Web: `KeyCreate` is `StrictBody` (extra `connect` field rejected, pushkey_local_api.py:85); `POST /api/keys` with overwrite rebuilds the entry with `"projects": []` (790-791) and drops connections; web inject uses `update_existing=False` and `.env` only (1011, `skipped_existing` in the response at 1017), so rotate never reaches files; `list_projects` returns `keys` computed from `vault[*].projects` only. `ProjectCard`/`ProjectPanel` key off `project.path` and render `name || path` (works for path-keyed entries; legacy name-keyed desktop entries appear as path="myapp").
12. Web bundle/tests: new routes also need `docs/local-api-v1.md` rows (contract tests); every `npm run build` changes the committed bundle + anchor; `node_modules` absent here so e2e/lint/build need `npm ci` (network); `local-vault.spec.ts` uses a Windows `.venv` python path; new add-key content is inside the existing axe scan (wcag.spec.ts:82) and needs mock routes.
13. New module registration: `pushkey_connect` must be added to `pyproject.toml` py-modules and `build_exe.py` SUBMODULES (test_package_metadata.py), plus `Pushkey.spec`.
14. Pre-existing bugs seen in passing (not caused by this work): `_do_env_import` treats `detect_provider`'s `str` as a dict (8233, 8267) and writes `"env": "production"` (8274); `PushkeyApp.reload_app` (8596) builds `AppFrame` without `vault_key`.
15. Env filter turns from a hard filter into a label: today `target_env` is enforced at write time (`_env_match` in `inject_env_file`, pushkey.py:1130-1136) and desktop default is "all" (7712, project form `self.proj_env.set("all")` at 7677). Spec 5.1 makes `environment` a warning-only label (default "dev") and 5.2 turns every `keys` entry into a connection, so keys that the env filter silently kept out of a project today would be written after migration unless migration drops/flags env-mismatched assignments. Also `add_key` default env is "all" (5831) vs web "dev".
16. Stale key names: `delete_key` never prunes `config["projects"][*]["keys"]` (see 1.0), so migration will meet assigned names that no longer exist in the vault; `sync_project`/`ci_sync_project` already tolerate them with `if k in self.vault` (7914, 8006).
17. User-facing copy promises the silent behaviour: help text `pushkey.py:2015-2027` ("Pushkey writes a .env file into the linked folder whenever you add or rotate a matching key"), the form label "TARGET ENV  (only inject keys matching this env)" (7670; help text 2022 says the same), the "Link a project folder" blurb, and the empty-state text at 7688 ("will auto-write .env files when you add or rotate keys"); all need rewording when the silent rules go.
18. Bundle churn: `build_exe.py` runs `npm run build` on every exe build (see section 5), so a dev who builds the exe also rewrites the committed bundle + anchor; keep that out of unrelated commits.
