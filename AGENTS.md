# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Commit & Identity Policy (mandatory)

- **Git identity:** always commit as `pushkeydev <pushkeydev@gmail.com>`. Never use `abrown18@gmail.com` or any other identity for this repo. Verify with `git config user.email` before any commit.
- **No AI attribution in commits:** do NOT append `Co-Authored-By: Claude`, `Generated with Claude Code`, `noreply@anthropic.com`, or any similar AI-tooling attribution to commit messages or PR bodies. Pushkey is shipped as `pushkeydev`'s work.
- **Client-integration references are allowed:** docs and code MAY mention "Claude Code" / "VS Code" / "Cursor" etc. as MCP client names — those are product integration references, not authorship. Only attribution/co-author lines are forbidden.

## Commands

```bash
# Run GUI
python pushkey.py

# Run CLI
python pushkey_cli.py --help

# Run all tests (107 tests)
pytest

# Single test file
pytest tests/test_vault_crypto.py -v

# Build Windows exes (GUI + CLI — clears dist/ automatically via --noconfirm)
python build_exe.py
# Output: dist/Pushkey.exe           (GUI, --onefile)
#         dist/pushkey-cli.exe      (CLI, --onefile)

# Cloud sync backend
uvicorn pushkey_cloud_api:app --host 0.0.0.0 --port 8000

# Web dashboard (Next.js)
cd web && npm run dev
```

No linting config — project uses no formatter/linter config files.

## Updating the Desktop Icon (Windows)

**CRITICAL — read this before touching the desktop icon. Six attempts failed because of folder confusion before this was documented.**

### Why this is non-obvious

1. **Desktop is OneDrive-redirected.** The user's real Desktop is `C:\Users\aware\OneDrive\Desktop`, NOT `C:\Users\aware\Desktop`. The latter exists but is empty/orphaned. Always resolve via `[Environment]::GetFolderPath('Desktop')` in PowerShell or `%USERPROFILE%\OneDrive\Desktop` — never hardcode `$env:USERPROFILE\Desktop`.
2. **The desktop "icon" is `Pushkey.exe` directly on the desktop**, not a `.lnk` shortcut. Editing shortcut properties does nothing because there is no shortcut. You must replace the `.exe` itself.
3. **Single-size `.ico` files render badly or fail.** Windows needs 16, 32, 48, and 256 px embedded in one file. PIL's `save(format='ICO')` only embeds the first size unless you pass `sizes=[...]` AND `append_images=[...]`.
4. **Windows aggressively caches icons.** Even after replacing the file correctly, the visual desktop won't update until both `IconCache.db` and `iconcache_*` files in `%LOCALAPPDATA%\Microsoft\Windows\Explorer` are deleted AND explorer is restarted. F5 alone is not enough.

### The full pipeline (do all 4 steps — skipping any one will fail)

**Step 1 — Copy the source `.ico` directly. DO NOT rebuild it through PIL.**

If the user's source already has multiple sizes embedded (check with `Image.open(path).info.get('sizes')`), just copy it byte-for-byte. PIL's `save(format='ICO')` strips sizes — a 9-size source becomes a 4-size output. Verify hashes match:
```bash
cp "<source.ico>" "C:/Users/aware/bots/pushkey/pushkey.ico"
python -c "import hashlib; print(hashlib.md5(open('C:/Users/aware/bots/pushkey/pushkey.ico','rb').read()).hexdigest())"
```
Only fall back to PIL conversion if the source is a single-size `.ico` or a `.png`.

**Step 2 — NUKE the PyInstaller build cache, then rebuild:**

PyInstaller caches the icon resource. Rebuilding without clearing `build/` and `Pushkey.spec` produces an `.exe` with the OLD icon, even though `pushkey.ico` on disk is new. This bug wasted 7+ build cycles before being identified.
```bash
rm -rf C:/Users/aware/bots/pushkey/build C:/Users/aware/bots/pushkey/dist C:/Users/aware/bots/pushkey/Pushkey.spec
cd C:/Users/aware/bots/pushkey && python build_exe.py
```

Verify by reading the icon resources from the freshly-built `.exe` (must show all sizes from your `.ico`, not just one):
```python
import pefile, struct
pe = pefile.PE('C:/Users/aware/bots/pushkey/dist/Pushkey.exe')
for r1 in pe.DIRECTORY_ENTRY_RESOURCE.entries:
    if r1.id == 3:  # RT_ICON
        for r2 in r1.directory.entries:
            for r3 in r2.directory.entries:
                raw = pe.get_data(r3.data.struct.OffsetToData, r3.data.struct.Size)
                if raw[:8] == b'\x89PNG\r\n\x1a\n':
                    print(struct.unpack('>I', raw[16:20])[0], 'PNG')
                else:
                    print(struct.unpack('<i', raw[4:8])[0], 'BMP')
```
If it prints fewer sizes than the source `.ico` had, the cache wasn't cleared — try again.

**Step 3 — Copy the fresh `.exe` over the desktop copy. Resolve real desktop via API:**
```powershell
Get-Process -Name "Pushkey" -ErrorAction SilentlyContinue | Stop-Process -Force
$realDesktop = [Environment]::GetFolderPath('Desktop')   # NOT $env:USERPROFILE\Desktop
Copy-Item "C:\Users\aware\bots\pushkey\dist\Pushkey.exe" (Join-Path $realDesktop "Pushkey.exe") -Force
```

**Step 4 — Wipe icon cache + restart explorer + notify shell:**
```powershell
Stop-Process -Name explorer -Force
Start-Sleep -Milliseconds 800
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Windows\Explorer" -Filter "iconcache*" -Force | Remove-Item -Force
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Windows\Explorer" -Filter "thumbcache*" -Force | Remove-Item -Force
Start-Process explorer.exe
Add-Type '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, int f, System.IntPtr a, System.IntPtr b);' -Name S -Namespace W
[W.S]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
```

### Verification (REQUIRED — do not declare success without this)

Extract the icon from the desktop `.exe` after the copy and read it back as PNG to confirm it matches the source:
```powershell
Add-Type -AssemblyName System.Drawing
$ico = [System.Drawing.Icon]::ExtractAssociatedIcon("C:\Users\aware\OneDrive\Desktop\Pushkey.exe")
$ico.ToBitmap().Save("C:\Users\aware\Downloads\verify_icon.png")
```
Then `Read` that PNG and visually confirm it matches the user's source. If they don't match, the file copy is wrong — do not blame caching until verification passes.

### Common failure modes (rule out in this order)

| Symptom | Cause | Fix |
|--------|-------|-----|
| Shortcut properties show new icon, desktop shows old | Wrote `.lnk` to `C:\Users\aware\Desktop` (orphan folder) | Use `[Environment]::GetFolderPath('Desktop')` |
| Multi-size source `.ico` ends up as 1 size in `.exe` | PyInstaller `build/` cache holds the previous icon | `rm -rf build dist Pushkey.spec` before rebuild |
| User's 9-size `.ico` becomes a 4-size `.ico` | PIL `save(format='ICO')` round-trip strips sizes | Copy source directly, never re-encode through PIL |
| `.exe` updated but Windows shows generic icon | Single-size `.ico` (e.g. only 250×250) | Use a real multi-size source or PIL fallback |
| New `.exe` built but desktop unchanged | Old `Pushkey.exe` sitting on desktop never got overwritten | Copy `dist/Pushkey.exe` to OneDrive desktop |
| File replaced correctly but icon still old visually | Icon cache | Wipe cache + restart explorer (step 4) |
| Still old after all of the above | Shell hasn't repainted | Tell user to press F5 on desktop or sign out/in |

## Architecture

**Modular app**: `pushkey.py` is the GUI entry point; core logic is split into focused submodules (see table below). All submodules import paths via `pushkey_shared` — never hardcode `~/.pushkey` paths.

### Crypto Layer

Two vault formats, both using `~/.pushkey/vault.enc`:

- **V2** (current): magic `PK2\x00`, AES-256-GCM, Argon2id KDF (time=3, mem=64MB, par=4) or PBKDF2 fallback at 600k iterations. Nonce is 12 bytes prepended to ciphertext.
- **Legacy V1**: Fernet (AES-128-CBC). Auto-detected on load, user prompted to migrate.
- **Team vault**: magic `PKT2`, ephemeral salt embedded in payload (not persisted to disk).

Log encryption uses a deterministic AESGCM key derived from the salt — no password needed to decrypt logs, intentionally.

Key derivation entry point: `derive_key(password, salt)` → 32 bytes (`pushkey_crypto.py`).
Vault entry point: `load_vault(password)` → `(dict, key)`, `save_vault(dict, password)` (`pushkey_vault.py`).

### Vault Data Model

`vault.enc` decrypts to a JSON dict:
```
{key_name: {value, created, rotated, provider, env, projects: [...], notes}}
```

`~/.pushkey/config.json` holds project paths and key assignments (encrypted separately).
`~/.pushkey/health.json` is a public sidecar — no secrets, just health status + timestamps.

### Tier/License System (`pushkey_tiers.py`)

`current_tier()` reads `~/.pushkey/.license` (AES-GCM encrypted). Feature gates call `can_do(feature)` and `within_limit(resource, count)` before allowing Pro/Team/Enterprise actions. Token refreshed every 24h via `maybe_heartbeat()`; 10-day offline grace period before downgrade to free.

Tier names: `free`, `starter`, `pro`, `team`, `enterprise`.

**Test coverage**: `tests/test_tiers.py` (23 tests) covers load, expiry, grace period, gates, heartbeat, and offline downgrade.

### Provider Detection (`pushkey_providers.py`)

`detect_provider(name, value=None)` matches key names via regex patterns in `providers.json` (32+ providers). Falls back to key value prefix matching (e.g., `sk-` → OpenAI). Remote registry fetched from GitHub with local cache fallback.

### UI Frame Structure

```
PushkeyApp
├── LoginFrame    # master password + TOTP/FIDO2 MFA
└── AppFrame      # left sidebar nav + stacked content frames (tkraise to switch)
    ├── Dashboard # neon stat cards, security score gauge, rotation rate gauge,
    │             # forecast heatmap + upcoming rotations, activity feed
    ├── All Keys  # search bar + env filter pills, grouped key rows with
    │             # health/env pills + inline action buttons
    ├── Projects  # status-pill cards (ACTIVE / NEEDS ASSIGN / EMPTY) with
    │             # icon-labeled action buttons
    ├── Security  # vault scan, git history scan, policy groups
    ├── Cloud     # sync status, devices, conflict resolution
    └── Timeline  # 3 sub-tabs:
        ├── Lifecycle  # card-per-key with filter pills (All/Critical/...)
        ├── Activity   # paginated audit log with category tags
        └── Forecast   # stat strip + 90-day heatmap + grouped due list
```

### UI / Theming Architecture

**Color system** (`pushkey.py:1929-1999`)
- `C_DARK` / `C_LIGHT` palettes with semantic tokens: `bg`/`bg2`/`bg3`/`bg4` (tier ladder),
  `surface`, `accent` (cyan), `violet`, `text`/`text2`/`text3` (hierarchy),
  `border`/`border2`, `btn`/`btn_hover`, semantic `green`/`amber`/`red`/`blue` plus `*_bg`
  dim variants used for tinted "neon" card surfaces, `env_*` pill colors.
- Active palette swapped via `set_theme()` → mutates global `C` dict + calls
  `ctk.set_appearance_mode()`.

**Icon system** (`pushkey_icons.py`)
- 27 Lucide-inspired stroke icons drawn at runtime via PIL primitives — no SVG/Cairo
  dep, fully offline. Each icon is a function `(d, s, c, w)` that strokes geometry on a
  transparent PIL image at requested size.
- Public API: `load_icon(name, size, color)` → PIL Image (cached per name+size+color).
- `pushkey.py` wraps it in `icon(name, size, color)` → `CTkImage` (also cached).
- **PyInstaller MUST be told about it via `--hidden-import`** because the import is wrapped in a try/except for dev resilience. All 6 submodules (`pushkey_shared`, `pushkey_crypto`, `pushkey_vault`, `pushkey_tiers`, `pushkey_providers`, `pushkey_icons`) are wired in `build_exe.py`.

**Theme switching** (`AppFrame._toggle_theme` → `_apply_theme_inplace`)
- Does NOT destroy + rebuild AppFrame (that was the old slowdown). Instead it
  recolors root + sidebar + content frames in place, marks every tab dirty, and
  re-renders only the active tab. Other tabs re-render on next visit.
- Use this pattern for any future global re-skin.

**Tab rendering**
- Lazy: `_NAV_RENDER` maps nav key → render method; `_tab_rendered` tracks which
  ones have been built; `_tab_dirty` tracks which need a re-render on next visit.
- Idle pre-render: 800ms after login, `_idle_prerender_tabs` schedules a
  non-blocking render of every non-active tab on a 250ms cadence so first-visit
  switches feel instant.
- `_invalidate_tabs(*tabs)` — call when state changes (key added, rotated, etc.)
  to mark relevant tabs dirty.

**Resize debouncer** (`_ResizeDebouncer` in `pushkey.py`)
- Coalesces `<Configure>` floods on root window to 100ms intervals so Canvas-heavy
  frames (gauges, heatmap, lifecycle) don't redraw on every pixel of resize.
- Available globally via `self.master._resize_debouncer.register(callback)`.

**Buttons**
- All buttons go through `make_btn(parent, text, command, ...)` (`pushkey.py:~2088`).
  Defaults: height=32, corner_radius=6, border_width=1 (light theme needs this so
  buttons don't blend into white surfaces). Pass `border=False` to opt out.

**Card layout pattern**
- Card with status accent: outer `CTkFrame(fg_color=status_col)` wrapping inner
  `CTkFrame(fg_color=C["surface"], padx=(4, 0))` produces a 4px colored left bar.
- Stat cards: tinted bg using semantic `*_bg` token + 2px border in metric color
  → "neon glow" effect. See dashboard Row 1 stat cards.
- Pills: `CTkFrame(fg_color=tinted_bg, corner_radius=8-10, border_width=1, border_color=accent)`
  with a single bold uppercase label inside.
- **Never** mix `pack(side=...)` and `.place(rely=0.5)` in the same row — children
  land on different baselines and the row's border looks broken (this was the
  All Keys card outline bug — see `_render_single_key`).

### Python Submodules

| Module | Purpose |
|--------|---------|
| `pushkey_shared.py` | Path constants + `TIERS` dict. Zero imports — safe base for all others. |
| `pushkey_crypto.py` | AES-256-GCM, Argon2id/PBKDF2 KDF, salt, log encryption |
| `pushkey_vault.py` | `load_vault` / `save_vault` / `load_config` / `save_config` |
| `pushkey_tiers.py` | License load/save, tier gates, heartbeat, offline grace |
| `pushkey_providers.py` | Provider detection, health status, `days_since` |
| `pushkey_icons.py` | 27 Lucide-style PIL icons, `load_icon(name, size, color)` |
| `pushkey_cli.py` | Standalone CLI — no tkinter. Entry point: `pushkey` (pip) or `pushkey-cli.exe` |
| `pushkey_cloud_api.py` | FastAPI sync backend — zero-knowledge vault storage |

### Subdirectory Submodules

| Path | Purpose |
|------|---------|
| `server/` | FastAPI zero-knowledge cloud sync backend (Railway-deployable) |
| `web/` | Next.js admin dashboard + landing page. Env: `NEXT_PUBLIC_ADMIN_API_URL`. Deployed via `vercel.json` at repo root. |
| `vscode-pushkey/` | VS Code extension — reads `~/.pushkey/health.json`, decorates editors |
| `browser-pushkey/` | Chrome/Edge MV3 extension — polls health server on port 7654 |

### Security Invariants

- Master password **never** stored; vault decrypted in memory only.
- Cloud sync sends only AES-GCM ciphertext — server is zero-knowledge.
- `.env` injection always adds `.env` to project's `.gitignore`.
- Audit log entries are individually encrypted (length-prefixed binary format).
- Team exports embed ephemeral salt in payload; recipient derives key from shared password, not persisted salt.

### Test Isolation

`tests/conftest.py` has an `autouse` fixture that monkeypatches all `pushkey_shared` path constants to `tmp_path` for every test. Because all submodules read paths via `pushkey_shared` at call time (not import time), this one patch point covers everything.

**Do not** monkeypatch `pushkey.*` path attrs in new tests — they're irrelevant since vault/crypto/tiers all use `pushkey_shared` directly.

Test files:
| File | Coverage |
|------|---------|
| `test_vault_crypto.py` | Vault round-trip |
| `test_encryption_edge_cases.py` | Edge-case values |
| `test_key_rotation.py` | Rotation timestamps, history |
| `test_env_injection.py` | `.env` merge, gitignore dedup |
| `test_multi_project.py` | Project link/unlink |
| `test_provider_detection.py` | Provider pattern matching |
| `test_providers.py` | `pushkey_providers` module (20 tests) |
| `test_cli.py` | CLI commands (26 tests) |
| `test_tiers.py` | License, tier gates, heartbeat (23 tests) |
| `test_ui_helpers.py` | `_log_line_age_days` |
