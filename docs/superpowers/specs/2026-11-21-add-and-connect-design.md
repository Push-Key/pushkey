# Add & Connect: one way to bring a key into Pushkey and into a project

Status: approved by the owner 2026-11-21, with the recommended answer to every
owner decision in section 7 (Q1-Q5). Scope of the build: section 6 steps 0 and 1
(phase 1). Phases 2 (browser) and 3 (phone) need their own specs.
Base: branch `feat/add-and-connect`, cut from PR #24 (`feat/agentic-auth-foundation`,
agent tokens and health sidecar v1 save path) with PR #25 (`fix/config-json-sniff`,
config nonce fix) merged in; both PRs are still open. Line references below are
`origin/main` at `ae7def7` unless they say otherwise; the plan re-checks them
against the branch.

## 1. Why

The owner wants several ways to bring a new API key into Pushkey: the desktop
app, the phone, the browser extension and a coding agent. All of them should end
the same way:

1. the key is saved in the vault,
2. it is connected to the right project,
3. it is written into the file that project actually reads, under the variable
   name the project's code expects,
4. Pushkey remembers that connection, so replacing the key later updates the
   project too,
5. each key shows where it is used and whether each project's copy is current.

Who it is for: a developer with several projects and providers, who today copies
keys by hand between provider dashboards, Pushkey and env files.

## 2. What exists today

Each line carries its probe.

- **Two project stores that do not see each other.**
  - Desktop app: `config.projects[NAME] = {path, keys, target_env}`
    (`pushkey.py:7842-7847`); assignments are saved only there (`pushkey.py:8149`).
  - CLI shell, web app and MCP: `config.projects[ABS_PATH] = {name, created}` and
    the assignment is the path stored in the key's own vault entry,
    `vault[KEY].projects` (`pushkey_cli.py:1285`, `pushkey_local_api.py:890`).
    MCP uses that list as its allowlist (`pushkey_mcp.py:70-71`).
  - So a key assigned in the desktop app is "not assigned" for CLI/MCP inject
    (`pushkey_mcp.py:315`), and the desktop auto-sync skips projects that have no
    `path` field (`pushkey.py:6329-6330`). The web app's path canonicalisation
    leaves name-keyed entries as they are (`pushkey_local_api.py:376-378`).
- **Desktop writes keys nobody picked.** Adding or replacing a key auto-writes into
  every project that lists it, and into every project whose list is empty; for an
  empty list it writes every vault key for that project's environment
  (`pushkey.py:6328`, `pushkey.py:1125-1126`). New projects are also auto-assigned
  every key whose name starts with the project name (`pushkey.py:8098-8101`).
- **Only one file, only one name.** Pushkey writes only `<project>/.env`
  (`pushkey_env.py:82`), and the variable name is always the vault key name.
- **Gitignore check is exact.** It looks for a line that is exactly `.env`
  (`pushkey_env.py:55`).
- **Existing bug, independent of this feature:** the desktop backs up the old
  `.env` as `.env.pushkey_backup_<timestamp>` next to it (`pushkey_env.py:112`).
  The `.env` gitignore line does not match that name, so those backups (full of
  secrets) can be committed. Fix separately, now.
- **Overwrite behaviour differs by entry point.** CLI and desktop replace a value
  already in `.env` (`pushkey_cli.py:550`, `pushkey.py:1133`); MCP and web-app
  inject skip it (`pushkey_mcp.py:334`, `pushkey_local_api.py:998`), so a replaced
  key never reaches the project through them.
- **Adding and connecting are separate steps everywhere.** The web app has three
  separate calls (`web-app/src/lib/api.ts:164,183,188`; whether a screen chains
  them is unchecked). The CLI shell is `project add` -> `project assign` -> `inject`
  (`pushkey_cli.py:1263-1290`).
- **`config.json` is not protected by the master password.** Its key is derived
  from the salt file on disk plus a fixed label (`pushkey_crypto.py:448-453`), so
  anyone who can read `~/.pushkey` can read and change it.
- **Replacing a key through "overwrite" drops its projects.** `POST /api/keys` and
  MCP `add_key` with overwrite rebuild the entry with `projects: []`
  (`pushkey_local_api.py:780`, `pushkey_mcp.py:279`).
- **Agents can already reach any folder.** MCP `assign_key` needs only the write
  scope and appends any resolved path to the key's allowlist, with no check that
  the folder is a registered project (`pushkey_mcp.py:546-562`). MCP `inject_env`
  does not need a registered project either, while the web app does
  (`pushkey_local_api.py:960-961`).
- **The web app already has a strict project-file writer**, `_atomic_project_write`
  (`pushkey_local_api.py:331-365`): it writes one named file directly in the
  registered folder through a temp file, checks the target with
  `_assert_project_target` against a pinned folder identity before and after the
  write, and refuses a temp file that turned into a link or reparse point. (The
  body of `_assert_project_target` was not read.)
- **The project limit per plan** (`max_projects`) is enforced only in the desktop
  (`pushkey.py:7834`); a grep for `max_projects`, `within_limit` and `can_do(` in
  the CLI, web app and MCP finds only `can_do("dual_rotation")`
  (`pushkey_mcp.py:446`).
- **Browser extension** reads key health only: permissions `storage`, `alarms`,
  host `127.0.0.1:7654` (`browser-pushkey/manifest.json:6-7`).
- **Phone:** no app, no pairing. The cloud API has licence device activation
  (`pushkey_cloud_api.py:1772`) but no route to relay a key, and the cloud API is
  not deployed.

## 3. Goals, non-goals, anti-goals

Goals

- G1. One project store, used by desktop, web app, CLI and MCP.
- G2. A saved **connection**: key + project folder + file + variable name.
- G3. One "add and connect" action that behaves the same in every entry point,
  with a preview line before anything is written, for example
  `Save to acme-web -> dev -> .env.local as NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- G4. Replacing a key updates every connected file.
- G5. Each key shows where it is used and whether each copy is current; each
  project shows its connections.
- G6. Browser extension (phase 2) and phone (phase 3) as entry points.

Non-goals for this spec

- An agent collecting keys from provider dashboards (needs per-provider
  integrations or browser automation; separate decision).
- A team-shared connection file committed to the repo (see approach C).
- Syncing connections between computers.
- Destinations other than dotenv files (JSON/YAML config, Vercel or GitHub
  secret stores).

Anti-goals: a failure even if everything "works"

- A key lands in a project the user did not confirm.
- A long-lived key value passes through an LLM chat (AGENTS.md policy).
- Pushkey changes lines it does not manage, or writes outside the project folder.
- Pushkey writes a secret file that git does not ignore.
- A key value appears in logs, the health sidecar, the audit log or an MCP reply.

## 4. Approaches

**A. Connections live on the key, inside the vault (recommended).**
`vault[KEY].connections = [...]`, next to the existing `projects` allowlist;
project display settings stay in `config.json`.
Gains: protected by the master password, in the same place as today's
allowlist; replacing a key needs only that key's entry; backups and exports carry
the connections. Cost: listing one project's connections scans all keys (a few
hundred at most; fine).

**B. Connections live on the project, in `config.json`.**
Gains: one read per project; close to the desktop's current shape. Cost:
`config.json` is not master-password protected (`pushkey_crypto.py:448-453`), so
anyone with file access could redirect which key is written to which file; and
"which keys go to this project" would again live in two places (config plus the
vault allowlist). Rejected.

**C. A manifest committed in each repo (`.pushkey.toml`: `VAR = KEY`).**
Gains: shareable with a team, travels with the code. Cost: a cloned repo could
ask for your keys, so it needs a trust prompt; it puts key names in git; and it
still needs A on each computer. Good later addition for teams; not first.

## 5. Design (approach A)

### 5.1 Data

Vault entry (encrypted with the master password):

```json
"SUPABASE_ANON_KEY": {
  "value": "...", "created": "...", "rotated": "...", "provider": "Supabase",
  "env": "dev", "notes": "",
  "projects": ["/home/me/code/acme-web"],
  "connections": [
    {"project": "/home/me/code/acme-web", "file": ".env.local",
     "var": "NEXT_PUBLIC_SUPABASE_ANON_KEY", "added": "2026-11-21T10:02:00"}
  ]
}
```

Rules:

- Every connection's `project` is also in `projects` (the allowlist stays the
  security check).
- `(project, file, var)` is unique across the vault: one variable in one file has
  one source key.
- `file` is a relative path that passes 5.4.

Config (`config.json`): `projects[<canonical absolute path>] = {name, created,
default_file, environment}`. `default_file` defaults to `.env`, `environment` to
`dev`.

My calls:

- No implicit connections. Migration (5.2) turns every existing assignment into
  an explicit connection `{file: ".env", var: KEY}`, which is what CLI and desktop
  inject write today, and they already replace the value (section 2). After
  migration, "assigned" always means "connected".
- `environment` is a label plus a warning, never a silent filter: when a key's
  `env` is neither the project's `environment` nor `all` (for example a `prod` key
  into a `dev` project), the preview says so and needs an extra confirm. The same
  rule holds in every entry point.
- Paths are per computer. A connection whose folder does not exist on this
  computer (after a backup import, or a future sync) shows "folder not on this
  computer" and is never written.

### 5.2 One project store, and migrating the desktop's projects

Runs once, the first time any Pushkey app with this feature unlocks the vault
(desktop, CLI, web app and MCP all call the same `pushkey_connect.migrate()`),
under the vault lock. It records `config.connect_schema = 1` when done, and every
step is safe to run again: old desktop entries are moved to `projects_legacy`,
so a second run finds nothing to move, and an assignment that already has a
connection gets no new one. That way keys a user unassigns later stay
unassigned even if the marker is lost. No marker goes into the vault: the CLI,
MCP and health code do not skip `_`-prefixed vault names (only the web app and
desktop do, e.g. `pushkey_local_api.py:649`, `pushkey.py:3793`), so a `_meta`
entry would show up as a key. Migration ships in the same release as the
desktop's switch to the new store (screens can come later), so no released
desktop writes the old shape after migration. (my calls)

1. For each desktop entry keyed by name with a `path`: create or merge
   `projects[canonical(path)]` with `name`, `environment = target_env`,
   `default_file = ".env"`. For each key in its `keys`, add the path to that key's
   `projects`. Then turn every assignment in the vault (desktop or CLI/web/MCP)
   into an explicit connection `{file: ".env", var: KEY}` (5.1). For desktop
   entries, only keys that passed the desktop's environment filter (project
   `target_env` is `all`, or the key's `env` is `all` or equal to it) are
   connected; the rest were never written by the desktop, so they stay
   unconnected and are listed in the notice. (plan restatement, 2026-11-21)

   Only a master-password session runs the migration. Agent-token and recovery
   sessions never write during unlock; until the store is migrated, their
   connect, assign, inject and sync calls answer "migration pending: open
   Pushkey with your master password once". A damaged or busy `config.json`
   never blocks unlock or key reads; migration is skipped for that unlock and
   only the project features refuse. (plan restatement, 2026-11-21)
2. An entry with an empty `keys` list (today: "receives every key"): **owner
   decision Q1**. Whatever the answer, the one-time notice shows in the desktop,
   the web app and the CLI, not only the desktop.
3. Save the vault first, then the config (the vault holds what matters for
   safety). Keep the old desktop entries under `projects_legacy` until the next
   successful save. (my call)
4. The desktop app moves to the path-keyed store and drops both silent rules: the
   "empty list means every key" rule and the name-prefix auto-assign
   (`pushkey.py:8098-8101`). Name matches become suggestions in the preview.
   (my call)

### 5.3 Core module `pushkey_connect.py`

Shared by every entry point; no UI code.

- `suggest(vault, config, key_name, value=None, cwd=None)`: project, file and
  variable candidates, each with a reason ("current folder", "found in
  .env.example").
- `preview(vault, config, key_name, project, file=None, var=None)`: the resolved
  values; the confirmation line; what will change in the file (add the variable,
  replace its value, no change); any gitignore change; conflicts. A variable
  already connected to another key is an error unless the caller passes
  `replace_source=True`.
- `connect(session, preview, value=None)`. Order:
  1. add or replace the key, if a value is given;
  2. add the allowlist entry and the connection;
  3. save the vault (and republish health, as every save does after PR #24);
  4. write the file;
  5. make sure git ignores it;
  6. write an audit event with names only.
  If step 4 or 5 fails, the vault keeps the connection, its status reads
  "not written: <reason>", and the result carries `written: false` plus the
  reason; `sync` retries it. The vault is never rolled back because of a file
  failure, the same rule `_persist_project_state` follows in
  `pushkey_local_api.py`.
  `pushkey_connect` owns the reload-change-save cycle; it never saves a caller's
  stale in-memory copy. It reloads the vault, applies the change and saves;
  `save_vault` checks the file's revision under its own lock and refuses a
  stale copy. On that conflict it reloads and retries once, then fails with
  "the vault changed elsewhere; try again". It does not hold the vault lock
  across the cycle: the existing lock is not re-entrant, and nesting it around
  `save_vault` deadlocks for 5 seconds (probed). (my call; plan restatement,
  2026-11-21)
- `sync(session, key_name=None, project=None)`: rewrite connected variables.
  Every entry point calls it after rotate, rotate-to-backup and promote.
  Whether it asks first is **owner decision Q2**. When the caller is an agent
  token without the inject scope, the rotate still succeeds and the result lists
  the files that were not updated. (my call)
- Replacing a key always uses rotate behaviour (history, `rotated`,
  `rotation_count`) and keeps `projects` and `connections`. The "overwrite"
  paths that rebuild the entry (section 2) are changed to do the same. (my call)
- `status(vault, config, key_name=None, project=None)`: reads the files and
  compares values in memory. States: `up_to_date`, `out_of_date`, `not_in_file`,
  `file_missing`, `folder_missing`, `not_ignored`, and `not_written` with a reason
  (a failed write, a refused path, a file tracked by git). The result never
  contains a value.
- `disconnect(session, key, project, file, var, remove_line=False)`.

### 5.4 Writing files

Generalise `pushkey_env.mutate_env_file` to take `env_file` (a relative path,
default `.env`) and a `var -> value` mapping. Keep its current care: touch only
managed variables, keep every other line, add new lines under
`# Managed by Pushkey`, write atomically.

- A connected variable's value is replaced; the connection declares it managed.
  Variables without a connection are never touched.
- Allowed file paths: relative; no `..`; the file name is `.env` or starts with
  `.env.` (`.env.local`, `.env.development.local`); subfolders are allowed
  (`apps/web/.env.local`). Other names: **owner decision Q3**.
- The strict rules of the web app's `_atomic_project_write`
  (`pushkey_local_api.py:331`) apply to every entry point and every segment of
  the path: no symlinks, junctions or reparse points anywhere below the project
  folder, each subfolder a real directory, the folder's identity pinned between
  check and write. A path that fails is refused, not followed. (my call)
- A file git already tracks (`git ls-files --error-unmatch`) is refused: "this
  file is committed to git; Pushkey will not write secrets into it". (my call)
- Never write `.env.example`, `.env.sample` or `.env.template`; they are usually
  committed. They are read-only inputs for suggestions. (my call)
- Gitignore: the project's own `.gitignore` always lists the file. A line covers
  it when it equals the relative path (with or without a leading `/`), or has no
  `/` and matches the file name as a pattern (`.env*`); otherwise Pushkey
  appends the exact relative path. Git itself is used only to refuse files it
  already tracks. Asking `git check-ignore` was dropped: it answers from the
  enclosing repository, which may not be the project's. (my call; plan
  restatement, 2026-11-21)
- Backups of a file before Pushkey changes it go outside the project, to
  `~/.pushkey/env-backups/<project id>/`, the last 3 per file. That removes the
  `.env.pushkey_backup_*` files from projects (the bug in section 2). (my call)

### 5.5 Suggestions

- Project: in the CLI and for agents, the current folder (offer to register it if
  it is not a project yet); in the desktop and web app, the last used project,
  then projects already connected to keys from the same provider. A suggestion
  is shown in the preview; nothing is picked silently.
- File: the project's `default_file`; if the project has none set,
  `.env.local` when `next.config.*` or `vite.config.*` exists in the folder,
  otherwise `.env`. (my call)
- Variable: names found in `.env.example`, `.env.sample` or the target file that
  match the provider's patterns (`providers.json`) and are not connected yet;
  otherwise the vault key name. Names are offered as found, never invented.
- Warning: when a key that must stay on the server (for example a Supabase
  service-role key, an OpenAI key) is mapped to a variable with a browser prefix
  (`NEXT_PUBLIC_`, `VITE_`, `PUBLIC_`), the preview says "this name is bundled
  into browser code" and needs an extra confirm. (my call)

### 5.6 Entry points

Phase 1

- **Desktop** (`pushkey.py`): the add-key window gets a "Connect to project"
  section (open by default when there is a suggestion; can be skipped) with
  project, file, variable and the preview line; the button reads "Save & connect".
  Key detail gets a "Used in" list with status pills, "Update now" and
  "Disconnect". The Projects tab lists each project's connections.
- **Web app** (`pushkey app`): the same screens. New routes, scope in brackets:
  `POST /api/connections/preview` [read], `POST /api/connections` [write+inject],
  `DELETE /api/connections` [write], `GET /api/connections?key=|project=` [read],
  `POST /api/connections/sync` [inject]. `POST /api/keys` accepts an optional
  `connect` object so one call does both.
- **CLI**: `pushkey add NAME [VALUE] [--project PATH] [--file F] [--as VAR] [--yes]`
  (VALUE becomes optional and is asked with getpass when left out; today it is
  required, which contradicts the MCP warning that already tells people to run
  `pushkey add NAME`), `pushkey connect NAME
  --project PATH [--file F] [--as VAR]`, `pushkey where NAME`,
  `pushkey sync [NAME]`, and the same in the shell. `inject` stays.
- **MCP**: `preview_connection(name, project_path, file=None, var=None)`,
  `connect_key(name, project_path, file=None, var=None)` (a name only, never a
  value), `key_usage(name)`. `rotate_to_backup` triggers `sync`. `add_key` keeps
  its plaintext warning. What an agent may connect on its own is **owner
  decision Q4**.
- **Project limit per plan**: whether `max_projects` applies in every entry point
  is **owner decision Q5**.

Phase 2: browser extension (own short spec)

A popup form, "Save to Pushkey": paste the key, or right-click selected text. The
provider is guessed from the tab's address. It shows the same preview and talks
to the running Pushkey app on loopback with a paired extension token that has
write scope only. No script reads pages in this phase. Open technical point:
`pushkey app` takes the first free port in 7654-7659 (`pushkey_cli.py:829`) while
the extension polls 7654 (`browser-pushkey/background.js:4`); which process owns
7654 when both run is unchecked.

Phase 3: phone (own spec)

Needs a transport that does not exist yet (no relay route in
`pushkey_cloud_api.py`; the cloud API is not deployed). Fixed now: the phone
encrypts the key end-to-end to the computer's key; the computer shows an
approval with the same preview; nothing is saved or written before approval.

Scan with the camera (owner request, 2026-11-21). Besides pasting, the phone
app offers "Scan key": point the camera at a key and the app reads it as text.
Requirements fixed now:

- Text recognition runs on the phone. The camera image is never saved (not to
  the gallery, not to app storage) and never uploaded; it is dropped as soon as
  the text is read.
- The app shows what it read in small groups, easy to compare with the source,
  and the user confirms or corrects it before anything else happens.
- Misreads are expected (`0`/`O`, `l`/`1`/`I`). The app checks the result
  against what Pushkey knows about the provider (prefix, length, allowed
  characters) and flags a mismatch instead of sending it.
- The scan screen carries one line of warning: a key on screen can be seen by
  people nearby and by screen recordings.
- After confirmation the flow is the normal phone flow: choose the computer and
  project, send end-to-end encrypted, approve on the computer.

Open for the phone spec: where the key usually is when the user photographs it
(another computer, a screen share, paper). If it is mostly on the user's own
computer, the browser extension or paste is faster and cannot misread. Also
open: an optional test call to the provider before saving, which would be
Pushkey's first network call to a provider.

### 5.7 Safety rules for every entry point

- A preview before every write. CLI `--yes` and MCP `connect_key` skip the
  interactive step but still return the preview in their output.
- Agents: `connect_key` needs write and inject scopes and never takes a value.
- Values never leave `pushkey_connect`: not in results, logs, health or audit.
- The desktop's silent rules are removed (5.2 step 4).

## 6. Order of work

0. Merge PR #24 and PR #25. Fix the `.env.pushkey_backup_*` gitignore bug.
1. Phase 1a: `pushkey_connect` + file writer + migration + the desktop's switch
   to the new store (no new screens yet) + CLI + MCP, in one release.
   Phase 1b: web-app routes and screens. Phase 1c: desktop screens.
2. Phase 2: browser extension.
3. Phase 3: phone.

## 7. Owner decisions (open)

Most important first.

- **Q4. What may an agent connect on its own?** Today any write-scoped agent
  token can allowlist any folder (`pushkey_mcp.py:546`). Recommended: an agent can
  connect keys only to projects a person added (in the app, web app or CLI); it
  cannot add project folders; `assign_key` and `inject_env` get the same rule.
  No per-connect approval prompt. Alternative: every agent connect waits for a
  person to approve it in the running app (safer, but needs the app open).
- **Q1. Desktop projects with an empty key list** (today they receive every key).
  Recommended: migrate them with no keys and show a one-time notice that names
  them, with a button to pick keys. Alternative: keep "every key" as an explicit,
  visible per-project switch.
- **Q2. Replacing a key.** Recommended: update every connected file at once and
  show a result per project ("acme-web .env.local updated; billing-api folder
  not on this computer"). Alternative: list the projects and ask first.
  Note: this includes projects connected through the web app or an agent. Those
  paths never replaced a value already in `.env` before (section 2), so for them
  this is new behaviour.
- **Q5. Project limit per plan.** Today only the desktop enforces it
  (`pushkey.py:7834`). Recommended: enforce it for new projects in every entry
  point; never remove projects during migration (someone over the limit keeps
  what they have but cannot add more). Alternative: drop the limit.
- **Q3. Which files Pushkey may write.** Recommended: `.env` and `.env.*` only,
  inside the project folder. Alternative: any relative path inside the folder.

## 8. Left to the builder

Screen layout and wording within the mockup's flow; when status refreshes; audit
event names; how suggestions break ties; test layout.

## 9. Mockup

Clickable mockup: https://claude.ai/artifact/6ER8ZCAh4SwExh7Rbaeedj (private to
the owner). It shows the recommended answers to Q1, Q2 and Q4.
