# CLI Onboarding Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a branded pre-unlock Pushkey CLI shell with onboarding copy, menu actions, compact returning-user header, and seamless handoff into the existing unlocked REPL.

**Architecture:** Keep all CLI flow logic inside `pushkey_cli.py`, reusing existing vault init, app launch, dashboard, and REPL helpers. Add a small persisted onboarding-state marker in the existing vault directory so first-run vs returning-user header behavior is state-based without introducing new packages.

**Tech Stack:** Python 3.12, argparse REPL CLI, existing Pushkey vault helpers, pytest

---

## Implementation Status Update

This plan has now been implemented and expanded beyond the original onboarding shell scope.

### Completed
- Added branded pre-unlock onboarding shell to `pushkey_cli.py`
- Added persistent onboarding marker behavior for first-run vs returning-user CLI experience
- Restored large Pushkey ASCII branding on the first onboarding screen
- Added desktop launch fallback support from the CLI
- Routed bare `pushkey` into the pre-unlock onboarding shell
- Added richer unlocked command-center dashboard with persistent branding
- Added quick actions for key tasks inside the unlocked vault
- Added first-class in-vault sections for:
  - Projects
  - Agents
  - Security / health
  - App launching
- Added inline explainers for:
  - project linking and `.env` injection flow
  - agent tokens, scopes, and revoke behavior
  - health states and backup staging
- Improved `pushkey app` launch behavior so the CLI no longer prints the unsafe bare local URL
- Improved web-app offline/API failure UX with recovery instructions in `web-app/src/app/page.tsx`

### Files updated during implementation
- `pushkey_cli.py`
- `tests/test_cli.py`
- `web-app/src/app/page.tsx`
- `tests/test_web_app_states.py`
- `pushkey.py`
- `tests/test_ui_helpers.py`

### Verification run
- `pytest -q tests/test_cli.py`
- `pytest -q tests/test_web_app_states.py tests/test_cli.py`
- `python -m py_compile pushkey_cli.py`
- `python build_exe.py --cli-only`

### Notes for commit / release
- The generated static web bundle under `pushkey_web/out/` and `pushkey_web/_manifest.py` changed as part of the CLI-only build because the bundled web app was rebuilt.
- Temporary local debug artifacts like `.local-api-7658.log`, `web-app/.next-dev.log`, and `web-app/.next-dev.pid` should not be committed.
- If desired, the next sensible step is to create a single commit covering the CLI command-center upgrades, onboarding polish, and web-app recovery UX improvements.

---

## File Map

- Modify: `pushkey_cli.py` — add pre-unlock shell, ASCII header, menu/help flow, desktop-launch helper, onboarding state marker, unlock handoff
- Modify: `tests/test_cli.py` — add focused CLI flow tests
- Possibly modify: `AGENTS.md` only if manual operator instructions need updating after implementation

---

### Task 1: Add onboarding header/state helpers

**Files:**
- Modify: `pushkey_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:
- first-run header mode when marker file is absent
- compact header mode when marker file exists
- helper that writes onboarding marker successfully
- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_cli.py -k onboarding`
Expected: FAIL because new helper functions do not exist yet

- [ ] **Step 3: Write minimal implementation**

Add small helpers in `pushkey_cli.py`, for example:
- `_cli_onboarding_marker_path()`
- `_has_seen_cli_onboarding()`
- `_mark_cli_onboarding_seen()`
- `_render_cli_header(first_run: bool)`

Header should:
- show larger ASCII/description on first run
- show compact Pushkey header on later runs

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_cli.py -k onboarding`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pushkey_cli.py tests/test_cli.py
git commit -m "feat: add cli onboarding header helpers"
```

### Task 2: Add pre-unlock shell/menu

**Files:**
- Modify: `pushkey_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add tests for a pre-unlock command dispatcher handling:
- `unlock`
- `init`
- `app`
- `desktop`
- `help`
- `exit`
- numeric aliases like `1`, `2`, `3`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_cli.py -k pre_unlock`
Expected: FAIL because dispatcher/menu logic does not exist

- [ ] **Step 3: Write minimal implementation**

Add helpers such as:
- `_print_pre_unlock_menu(has_vault: bool)`
- `_print_pre_unlock_help()`
- `_dispatch_pre_unlock_command(...)`
- `_pre_unlock_shell(args)`

Behavior:
- default primary action is unlock when vault exists
- create/init path visible when vault missing
- menu accepts both numbers and command words
- help shows basic actions first, advanced commands below

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_cli.py -k pre_unlock`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pushkey_cli.py tests/test_cli.py
git commit -m "feat: add pre-unlock cli shell"
```

### Task 3: Add desktop launch fallback behavior

**Files:**
- Modify: `pushkey_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add tests for desktop launch helper choosing:
- installed `pushkey-gui` if available
- desktop `Pushkey.exe` if available
- whichever exists first
- clean error message if neither is available

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_cli.py -k desktop_launch`
Expected: FAIL because helper does not exist

- [ ] **Step 3: Write minimal implementation**

Add helper like `_launch_desktop_app()` using subprocess/path checks only. Reuse it from pre-unlock menu.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_cli.py -k desktop_launch`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pushkey_cli.py tests/test_cli.py
git commit -m "feat: add desktop launch fallback for cli"
```

### Task 4: Handoff from pre-unlock shell into existing unlocked REPL

**Files:**
- Modify: `pushkey_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:
- successful unlock path entering the existing dashboard/REPL flow
- wrong password showing error and staying in pre-unlock shell
- first successful unlock marking onboarding as seen

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_cli.py -k unlock_handoff`
Expected: FAIL because main flow still jumps directly to `_repl()`

- [ ] **Step 3: Write minimal implementation**

Refactor current bare-command flow in `main()` so:
- `args.command is None` enters `_pre_unlock_shell(args)` instead of `_repl(args)` directly
- successful unlock calls existing dashboard/REPL code without duplicating logic
- existing subcommands remain unchanged

Prefer extracting existing unlocked REPL body into a helper if needed rather than duplicating code.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_cli.py -k unlock_handoff`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pushkey_cli.py tests/test_cli.py
git commit -m "feat: route bare pushkey through onboarding shell"
```

### Task 5: Full CLI verification

**Files:**
- Modify: `tests/test_cli.py` if final coverage gaps appear

- [ ] **Step 1: Run focused CLI tests**

Run: `pytest -q tests/test_cli.py`
Expected: PASS

- [ ] **Step 2: Run packaging smoke for CLI entrypoint**

Run: `pushkey --help`
Expected: help text prints successfully

- [ ] **Step 3: Run manual shell smoke checks**

Verify manually:
- `pushkey` shows onboarding shell/header
- `help` works before unlock
- `app` launches web app
- `desktop` attempts desktop launch
- unlock enters existing REPL/dashboard

- [ ] **Step 4: Rebuild CLI/desktop artifacts if needed**

Run: `python build_exe.py`
Expected: build completes successfully

- [ ] **Step 5: Commit**

```bash
git add pushkey_cli.py tests/test_cli.py
git commit -m "feat: add guided onboarding shell to pushkey cli"
```
