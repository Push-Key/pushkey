# Pushkey Baseline Verification

Date: 2026-07-20  
Branch: `feat/pushkey-app`  
Starting commit: `f0b52ce24fedfa669c6f2c5b7307fe2028004469`  
Baseline tag: `production-readiness-baseline-20260720`

## Outcome

The Phase 0 verification commands complete successfully in an isolated Python
environment. The previous test "hangs" were command time limits shorter than
the real cryptographic suite runtime. Verification exposed and fixed four genuine
baseline defects:

- canonical licensing contract tests still used the removed
  `X-Admin-Secret` authentication path;
- unconstrained bcrypt 5.0 was incompatible with Passlib 1.7.4;
- the admin frontend used an empty readiness value after session validation,
  which prevented authenticated pages from loading data; and
- pytest retention settings and a copied read-only integrity manifest left
  temporary test trees behind on Windows.

The licensing tests now use the administrator session cookie and CSRF contract.
New cloud account and administrator password hashes use Argon2id. Legacy bcrypt
hash verification remains available, with bcrypt constrained below 5.0.
Authenticated admin pages now receive a non-secret readiness sentinel. Passing
tests remove their temporary directories, while failed tests retain diagnostics.

## Host and toolchain

| Component | Verified version |
|---|---|
| Operating system | Windows 11 Home 64-bit, version 10.0.26200, build 26200 |
| Python | 3.12.10 |
| pip | 26.1.2 |
| Node.js | 24.12.0 |
| npm | 11.6.2 |

Python verification used the ignored repository environment at `.venv`.
Dependencies were installed from `requirements.txt`, `requirements-api.txt`,
and `requirements-dev.txt`. `pip check` reported no broken requirements.

## Python dependency baseline

| Package | Version |
|---|---|
| FastAPI | 0.139.2 |
| Starlette | 1.3.1 |
| Pydantic | 2.13.4 |
| Uvicorn | 0.51.0 |
| cryptography | 49.0.0 |
| argon2-cffi | 25.1.0 |
| Passlib | 1.7.4 |
| bcrypt | 4.3.0 |
| python-jose | 3.5.0 |
| pytest | 8.4.2 |
| MCP | 1.28.1 |
| CustomTkinter | 6.0.0 |

The complete frontend dependency graphs remain locked in
`web/package-lock.json` and `web-app/package-lock.json`.

## Test results

Collection command:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
```

Result: 335 tests collected in 0.70 seconds.

Full command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --durations=30 --durations-min=0.1
```

Result:

- Passed: 334
- Failed: 0
- Errors: 0
- Skipped: 1
- Warnings: 2
- Runtime: 127.61 seconds

The skip is `test_inject_rejects_env_symlink` when Windows symlink creation is
unavailable. This is a narrow platform condition in the test, not a broad suite
exclusion.

The slowest recorded durations were:

| Test | Phase | Duration |
|---|---|---:|
| `test_project_state_persists_across_disk_reload` | call | 3.89s |
| `test_rekey_with_recovery_code` | call | 3.06s |
| `test_delete_project_clears_assignments` | call | 2.71s |
| `test_unassign_keys` | call | 2.62s |
| `test_rekey_wrong_recovery_code` | call | 2.24s |
| `test_inject_skips_existing_env_keys` | call | 1.93s |
| `test_rotate_to_backup_promotes_and_clears_slot` | call | 1.88s |
| `test_unlock_bad_password` | call | 1.88s |
| `test_gitignore_failure_prevents_env_secret_write` | call | 1.87s |
| `test_rotate_key_updates_value` | call | 1.86s |

The suite exited normally. No pytest, Uvicorn, or local API process remained.
The static-manifest cleanup regression test also leaves zero entries under
`.pytest_tmp`. No test required a broader timeout, skip, or weakened security
setting.

## Build and static validation

| Validation | Result |
|---|---|
| Python compileall for `pushkey*.py` and `server/` | Passed |
| `web-app`: `npm run build` | Passed |
| `web-app` static integrity generation | Passed, 30 assets |
| `web`: `npm run lint` | Passed after removing one unused parameter warning |
| `web`: `npm run build` | Passed, 32 pages generated |
| `git diff --check` | Passed |

The packaged local web output and its trust-anchor hash were refreshed by the
successful `web-app` production build.

## Known warnings and remaining gates

Two upstream deprecations remain visible in the isolated test run:

- FastAPI currently bridges its TestClient through deprecated `httpx` support
  while the ecosystem moves to `httpx2`.
- Passlib 1.7.4 reads the deprecated `argon2-cffi` package version attribute.

Neither warning changes runtime behavior in this baseline. They must remain
visible until the dependency stack is migrated or upgraded. They are not hidden
with warning filters.

The logical baseline commits, clean working tree, and tag named above close the
Phase 0 gate. Phase 1 still requires the versioned local API and health sidecar
contracts plus final legacy backend disposition. Phase 2 still requires the
complete local journey, subprocess CLI, shell completion, shared environment
mutation, secret leak, and repair documentation gates.
