# Pushkey Implementation Status

**Updated:** 2026-07-20
**Active branch:** `feat/agentic-auth-foundation`
**Baseline branch:** `feat/pushkey-app` at `5ef2f81`
**Last verified implementation commit:** `2881eca`

## Current Position

| Measure | Status |
|---|---|
| Verified production checklist | 27/340, 7.9% |
| Completed production phase gates | 1/13, 7.7% |
| Phase 0 baseline | Complete |
| CP1 health sidecar | **Complete** |
| Agentic authorization design | Complete and approved |
| Agentic authorization implementation plan | Complete and approved |
| Authorization implementation | Not started (CP1 prerequisite satisfied) |

## Verified Baseline

- Python suite: 441 passed, 10 platform skips (CP1 final full suite).
- VS Code contract: 10 passed.
- Browser contract: 6 passed.
- Packaging import/build-declaration: 4 passed.
- Both Next.js production builds passed.
- CLI executable built and verified.
- Baseline tag: `production-readiness-baseline-20260720`.

## Approved Specifications

- `docs/superpowers/specs/2026-07-20-health-sidecar-v1-design.md`
- `docs/superpowers/specs/2026-07-20-agentic-authorization-foundation-design.md`

## Approved Execution Plans

- `docs/superpowers/plans/2026-07-20-health-sidecar-v1.md`
- `docs/superpowers/plans/2026-07-20-agentic-authorization-foundation.md`

## Immediate Next Gate

CP1 complete. Begin CP2, roadmap accounting and Agentic Vision tracking:

1. Update the production readiness plan with CP2 scope and tasks.
2. Record permission catalog and Agentic Vision tracking requirements.
3. CP2 is documentation-only and does not modify code.

## Remaining Authorization Gates

| Gate | Deliverable | Authorization verification |
|---|---|---:|
| CP2 | Roadmap accounting, Agentic Vision tracking, permission catalog | Documentation only |
| CP3 | Token v2, locking, restrictive migration | 20% |
| CP4 | Project/path identity and policy evaluation | 40% |
| CP5 | Atomic reservation, journal, and audit projection | 60% |
| CP6 | MCP enforcement and API, CLI, web lifecycle parity | 80% |
| CP7 | Adversarial verification, builds, packaging, threat review | 100% |

## Resume Procedure

1. Start from this branch and confirm `git status --short --branch` is clean.
2. CP1 is complete. Begin CP2 (roadmap accounting, Agentic Vision tracking).
3. CP1 commit history includes `1641886` through `2881eca` (Tasks 1-8).
4. Use a fresh implementation subagent and two independent reviews per completed task.
5. Do not begin authorization implementation until CP2 completes.
6. Preserve the required Git identity: `pushkeydev <pushkeydev@gmail.com>`.

## Task 3 Boundary Follow-up

- GUI sidecar publication now records only `health_publication_failed` for
  typed health errors. The audit event contains no health-path details, key
  names, or values.
- Recovery-password reset now completes with a safe health-refresh warning when
  post-replacement invalidation fails, rather than allowing a GUI callback
  exception after the vault changes.
- Local API rekey and backup import map typed health invalidation and vault-lock
  failures to `503 health sidecar unavailable`.
- Local API recovery-code addition now locks the active session and returns the
  same sanitized `503` when post-replacement sidecar invalidation fails.
- Corrective post-commit replacement coverage:
  `python -m pytest tests/test_local_api.py -k "rekey_health_failure_locks_existing_session or backup_import_health_failure_locks_existing_session or recovery_add_health_failure_locks_existing_session or rekey_with_recovery_code or backup_import_replaces_vault" -v`
  produced `5 passed, 90 deselected` with two FastAPI deprecation warnings.
- Focused verification after this follow-up:
  `python -m pytest tests/test_ui_helpers.py tests/test_local_api.py tests/test_health_sidecar.py tests/test_vault_crypto.py -v`
  produced `203 passed, 8 skipped` with two FastAPI deprecation warnings.

## Task 4 Integration

- Normal plaintext-aware GUI, CLI, MCP, and local API mutation paths now use
  the shared post-save publisher. Publication failure is a stable sanitized
  `health_publication_failed` warning and never reverses a committed vault save.
- The GUI refreshes health every six hours only while its unlocked frame exists;
  locking cancels the scheduled refresh.
- The loopback `/health` endpoint serves only canonical, validated v1 bytes.
  Missing, invalid, stale, future-skewed, or oversized data returns the fixed
  `503 {"error":"health_unavailable"}` response. It sends no wildcard CORS,
  uses `application/json; charset=utf-8`, `Cache-Control: no-store`, and
  `X-Content-Type-Options: nosniff`, and rejects non-GET methods.
- Verification: the Task 4 interface suite produced `23 passed, 128 deselected`
  with two FastAPI deprecation warnings. The pre-existing multiprocess publisher
  test had one transient Windows sharing failure in an aggregate run and then
  passed in isolation (`1 passed`).

## Task 4 Compliance Closure

- Commits `3ded3db` and `36cb9f4` close the final Task 4 review findings.
- The Local API initialization path now publishes through the shared post-save
  hook. Every Local API mutation that invokes this hook returns the fixed,
  sanitized `X-Pushkey-Warning: health_publication_failed` header when
  publication cannot complete. This preserves existing JSON payloads and also
  covers `204` mutation responses without exposing an exception or secret.
- Desktop shutdown cancels the active AppFrame six-hour health refresh before
  destroying the root window.
- Loopback HTTP evidence now covers malformed, stale, future-skewed, and
  oversized sidecars, exact `Content-Length`, and non-GET `405` rejection.
- Focused compliance suite:
  `python -m pytest tests/test_health_sidecar.py tests/test_ui_helpers.py tests/test_local_api.py -k "loopback or health_publication_warning or shutdown_cancels or health" -v`
  produced `80 passed, 7 skipped, 95 deselected` with two FastAPI deprecation
  warnings.
- Task 4 interface suite:
  `python -m pytest tests/test_health_sidecar.py tests/test_cli.py tests/test_mcp.py tests/test_local_api.py -k "health or backup" -v`
  produced `89 passed, 7 skipped, 128 deselected` with two FastAPI deprecation
  warnings.
- Tray Quit now routes through the same scheduled callback used by the menu and
  cancels the active health refresh before exit handling or root destruction.
  The focused tray ordering regression test is in `tests/test_ui_helpers.py`.

## Commit History

- `52c7f15` Order health publication with vault replacement
- `6f8d158` Clarify health sidecar compatibility guarantees
- `251c831` Design health sidecar v1 contract
- `5ef2f81` Plan agentic authorization implementation
- `7b80d24` Design agentic authorization foundation
- `92888ea` Phase 0 baseline documentation

## External Release Requirements

CP1 through CP7 complete the agentic authorization foundation. Full product production readiness still requires the remaining Phase 1 through Phase 12 work in `docs/PRODUCTION_READINESS_PLAN.md`, including cloud architecture, administrative security, durable sync, operations, legal/support readiness, independent security review, and release sign-off.
