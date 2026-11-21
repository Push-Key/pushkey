# Pushkey Phase 2 Execution Tasklist

Status date: 2026-07-21

Purpose: move Phase 2 local security hardening forward with small, assignable
coding tasks. Use this file to dispatch low-cost workers without overlapping
file ownership.

## Current Phase 2 Wins

- [x] MCP plaintext write tools return warning fields.
- [x] MCP `inject_env` does not return `NAME=value`.
- [x] MCP `rotate_to_backup(name)` no longer returns `old_value_hint` or secret prefixes.
- [x] Local API project injection no longer returns `NAME=value` in responses.
- [x] Local API contract and route guard tests exist.
- [x] CLI, MCP, local API, and GUI injection share `pushkey_env.py`.
- [x] MCP injection requires assigned project paths.
- [x] MCP hostile key-name and newline-value tests exist.
- [x] Local API lifespan shutdown clears sessions and plaintext vault state.

## Next Worker Queue

### Worker 1: MCP Agent Token Expiration

Recommended model: `gpt-5.5`, low reasoning.

Owned files:

- `pushkey_agent_tokens.py`
- `tests/test_agent_tokens.py`
- `tests/test_mcp.py` only if MCP enforcement needs a focused regression

Goal:

- Add `expires_at` or equivalent expiry metadata to agent tokens.
- Enforce expiration during token verification/use.
- Preserve existing scope, revocation, and `last_used` behavior.

Acceptance:

- [x] Existing agent-token tests pass.
- [x] New test proves expired token is rejected.
- [x] New test proves valid non-expired token still works.
- [x] New test proves legacy tokens migrate or remain safely constrained.

Suggested command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_tokens.py tests\test_mcp.py -q
```

### Worker 2: CLI `set-backup`

Recommended model: `gpt-5.5`, low reasoning.

Owned files:

- `pushkey_cli.py`
- `tests/test_cli.py`
- `SECURITY.md` only if command wording needs alignment

Goal:

- Add `pushkey set-backup <NAME>` using `getpass` for production-safe backup staging.
- Do not print the backup value.
- Keep MCP guidance accurate: production secrets should be pre-staged through CLI, then promoted by name through MCP.

Acceptance:

- [x] Parser exposes `set-backup`.
- [x] Interactive value entry uses `getpass`.
- [x] Test proves `next_value` is written.
- [x] Test proves the secret value is not printed.

Suggested command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
```

### Worker 3: Stable CLI Exit Codes

Recommended model: `gpt-5.5`, low reasoning.

Owned files:

- `pushkey_cli.py`
- `tests/test_cli.py`
- `docs/PHASE2_EXECUTION_TASKLIST.md` for status only

Goal:

- Introduce named exit-code constants for success, usage, auth, I/O, corruption, and network failures.
- Apply them to obvious CLI error exits without broad refactoring.

Acceptance:

- [x] Constants exist in `pushkey_cli.py`.
- [x] Existing CLI tests pass.
- [x] Focused tests cover at least usage/auth/I/O style failures.

Suggested command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py -q
```

### Worker 4: Local API Injection Atomicity Failure

Recommended model: `gpt-5.6-luna` or `gpt-5.6-terra`, medium reasoning.

Owned files:

- `pushkey_local_api.py`
- `tests/test_local_api.py`

Goal:

- Fix `tests/test_local_api.py::test_gitignore_failure_prevents_env_secret_write`.
- Ensure `.gitignore` failure prevents `.env` secret write.
- Preserve existing symlink and project-target protections.

Acceptance:

- [x] Failing test passes.
- [x] Focused injection tests pass.
- [x] No plaintext secret appears in API injection response.

Suggested command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_local_api.py::test_gitignore_failure_prevents_env_secret_write tests\test_local_api.py::test_inject_preview_does_not_write tests\test_local_api.py::test_inject_writes_env_and_gitignore -q
```

### Worker 5: Shared Atomic Env Mutation Service

Recommended model: `gpt-5.6-terra`, medium reasoning.

Owned files:

- New helper module if needed, for example `pushkey_env.py`
- `pushkey_cli.py`
- `pushkey_mcp.py`
- `pushkey_local_api.py`
- Relevant tests

Goal:

- Consolidate CLI, MCP, and local API `.env` mutation into one tested service.
- Enforce consistent `.gitignore` ordering, symlink rejection, and failure atomicity.

Acceptance:

- [ ] CLI, MCP, and local API injection tests pass.
- [ ] Shared helper has focused tests.
- [ ] No response path returns plaintext `NAME=value` except commands explicitly intended to reveal secrets.

This worker should start only after Worker 4 is complete.

## Do Not Start Yet

- Database/object-storage migration.
- Distributed rate limiting.
- Admin MFA UI.
- Release signing workflow.

These depend on Phase 1/3/4 decisions and should not consume low-cost workers
yet.

## Next Dispatch Order

1. Worker 1, MCP agent token expiration.
2. Worker 2, CLI `set-backup`.
3. Worker 4, local API injection atomicity.
4. Worker 3, stable CLI exit codes.
5. Worker 5, shared env mutation service.
