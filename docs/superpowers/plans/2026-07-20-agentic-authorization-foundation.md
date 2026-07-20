# Agentic Authorization Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Pushkey's coarse agent scopes with a versioned, deny-by-default authorization foundation that supports constrained token v2 credentials, verified project identity, atomic use reservation, durable audit intent, and safe MCP enforcement without exposing plaintext through normal agent access.

**Architecture:** Add focused permission, policy, path-identity, locking, authorization, and audit modules around the existing encrypted agent-token store. MCP is the only agent-token execution interface in this milestone; the local API, CLI, and web app share caller-bound token lifecycle services. Every protected MCP operation rechecks current token state and records one atomic use reservation plus authorization intent before touching a protected resource.

**Tech Stack:** Python 3.12, pytest, AES-GCM storage through existing Pushkey crypto helpers, FastAPI/TestClient, MCP FastMCP, argparse, Next.js 16, React 19, TypeScript, PowerShell verification commands.

---

## Execution Gates

1. `docs/superpowers/specs/2026-07-20-agentic-authorization-foundation-design.md` is the controlling specification.
2. CP1, the `health.json` v1 sidecar contract, is an independent prerequisite. It needs its own approved design and implementation plan before authorization implementation starts.
3. Begin from commit `7b80d24` or a descendant with a clean working tree.
4. Verify Git identity is `pushkeydev <pushkeydev@gmail.com>` before every commit.
5. Preserve the Phase 0 baseline: 334 passing tests, one justified platform skip, both Next.js builds passing, and no retained passing-test artifacts.
6. Do not add approval persistence, `pushkey run`, provider brokers, agent-token delegation, remote MCP, network policy, or sandbox execution.

## Starting Completion Snapshot

| Measure | Starting value |
|---|---:|
| Verified production checklist | 23/340, 6.8% |
| Completed production phase gates | 1/13, 7.7% |
| Authorization design | 100% |
| Existing agentic prototype estimate | 20-25% |
| Authorization implementation | 0% |
| Authorization production verification | 0% |

The roadmap progress command added in Task 1 becomes authoritative for later
production percentages. Agentic post-launch work uses a separate denominator.

## File Map

### New modules

- `pushkey_permissions.py`: permission-set constants, action mapping, grant validation, and simple secret glob matching.
- `pushkey_locking.py`: bounded cross-process file lock for Windows and POSIX.
- `pushkey_path_identity.py`: canonical project registry, migration, tombstones, moves, and path verification.
- `pushkey_policy.py`: pure authorization request evaluation and structured decisions.
- `pushkey_authorization.py`: token reload, atomic reservation, authorization journal, operation completion, and audit projection retry.
- `pushkey_audit.py`: structured, redacted authorization-event projection into the existing encrypted log.
- `scripts/roadmap_progress.py`: reproducible production and agentic checklist percentages.

### New focused tests

- `tests/test_roadmap_progress.py`
- `tests/test_permissions.py`
- `tests/test_agent_token_v2.py`
- `tests/test_path_identity.py`
- `tests/test_policy.py`
- `tests/test_locking.py`
- `tests/test_authorization.py`
- `tests/test_mcp_authorization.py`
- `tests/test_cli_agents.py`

### Existing files changed

- `pushkey_shared.py`
- `pushkey_agent_tokens.py`
- `pushkey_vault.py`
- `pushkey_mcp.py`
- `pushkey_local_api.py`
- `pushkey_cli.py`
- `pushkey.py`
- `pushkey_crypto.py`
- `tests/conftest.py`
- `tests/test_agent_tokens.py`
- `tests/test_mcp.py`
- `tests/test_local_api.py`
- `tests/test_cli.py`
- `web-app/src/lib/api.ts`
- `web-app/src/components/agents-tab.tsx`
- `pyproject.toml`
- `build_exe.py`
- `docs/PRODUCTION_READINESS_PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/AGENTIC_VISION.md`
- `SECURITY.md`
- `docs/mcp-setup.md`

## Checkpoint Percentages

The authorization implementation percentage is checkpoint-based:

| Gate | Verification target | Authorization verified |
|---|---|---:|
| CP2 | Roadmap, Agentic Vision, and progress accounting | Documentation only |
| CP3 | Token v2 and restrictive legacy migration | 20% |
| CP4 | Permission policy and project/path identity | 40% |
| CP5 | Atomic reservation, journal, and audit projection | 60% |
| CP6 | MCP enforcement plus lifecycle parity | 80% |
| CP7 | Adversarial matrix, full suite, builds, and threat-model review | 100% |

After every checkpoint run:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git status --short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Record the exact new denominator and percentage in the checkpoint commit or
status document. Never substitute weighted engineering progress for verified
production completion.

### Task 1: Add Reproducible Roadmap Progress And Agentic Task Tracking

**Files:**
- Create: `scripts/roadmap_progress.py`
- Create: `tests/test_roadmap_progress.py`
- Create: `docs/AGENTIC_VISION.md`
- Modify: `docs/PRODUCTION_READINESS_PLAN.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Write the failing parser tests**

Create fixtures in `tests/test_roadmap_progress.py` proving that production
tasks, phase gates, and an explicitly marked post-launch agentic block are
counted separately:

```python
from scripts.roadmap_progress import calculate_progress


def test_progress_separates_launch_and_postlaunch_tasks():
    text = """
# Phase 0
- [x] baseline
# Phase 1
- [ ] contract
<!-- agentic-postlaunch:start -->
- [ ] provider brokers
<!-- agentic-postlaunch:end -->
"""
    result = calculate_progress(text)
    assert result["production"] == {"done": 1, "total": 2, "percent": 50.0}
    assert result["agentic_postlaunch"] == {
        "done": 0, "total": 1, "percent": 0.0
    }
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_roadmap_progress.py -v
```

Expected: FAIL because `scripts.roadmap_progress` does not exist.

- [ ] **Step 3: Implement the minimal parser and CLI**

Implement `calculate_progress(text)` with `^- \[([ xX])\]` matching and explicit
agentic-postlaunch markers. The CLI reads
`docs/PRODUCTION_READINESS_PLAN.md`, prints JSON with `--json`, and otherwise
prints counts and one-decimal percentages. It exits nonzero for missing or
malformed markers.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_roadmap_progress.py -v
```

Expected: PASS.

- [ ] **Step 5: Add the approved Agentic Vision**

Create `docs/AGENTIC_VISION.md` from the approved source at:

```text
C:\Users\aware\.codex\attachments\71662b03-a6fc-4620-9d31-62ffdc0cadfe\pasted-text.txt
```

Normalize the file to UTF-8 and replace mojibake, typographic dashes, and arrow
glyphs with clear ASCII prose. Preserve the product position, six pillars, MCP
architecture, sequencing, backlog, success criteria, defensible claims, risks,
and final direction. Add a note that the controlling authorization details are
in the approved specification.

- [ ] **Step 6: Update the production roadmap**

In `docs/PRODUCTION_READINESS_PLAN.md`:

- add a dated progress snapshot generated by the script;
- expand existing Phase 2 agent-token tasks instead of duplicating them;
- add CP2 through CP7 with evidence links;
- add a separately marked post-launch Agentic Vision block;
- state that advanced agent work is not a launch gate; and
- keep CP1 as an independent Phase 1 prerequisite.

Update `docs/ARCHITECTURE.md` with the new authorization module ownership and
MCP-only agent-operation boundary.

- [ ] **Step 7: Validate percentages and document text**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$badText = rg -n "\x{00E2}|\x{2014}|\x{2013}" docs\AGENTIC_VISION.md docs\PRODUCTION_READINESS_PLAN.md docs\ARCHITECTURE.md
if ($LASTEXITCODE -eq 0) { $badText; throw "invalid production document text" }
if ($LASTEXITCODE -ne 1) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: progress output includes prior and new denominators; `rg` returns no
matches; diff check passes.

- [ ] **Step 8: Commit CP2**

```powershell
git config user.name pushkeydev
git config user.email pushkeydev@gmail.com
git add scripts/roadmap_progress.py tests/test_roadmap_progress.py docs/AGENTIC_VISION.md docs/PRODUCTION_READINESS_PLAN.md docs/ARCHITECTURE.md
git commit -m "Document agentic authorization roadmap"
```

### Task 2: Implement The Versioned Permission Catalog

**Files:**
- Create: `pushkey_permissions.py`
- Create: `tests/test_permissions.py`
- Modify: `pyproject.toml`
- Modify: `build_exe.py`

- [ ] **Step 1: Write failing permission and glob tests**

Cover valid issuable permissions, reserved permissions, unknown action denial,
case-sensitive whole-name matching, `*` and `?`, rejected character classes,
required selector dimensions, canonical environments (`dev`, `test`, `staging`,
`prod`, `all`), rejection of unknown environments, explicit wildcards,
rejection of `"*"` mixed with concrete entries in one selector array,
duplicate grant IDs, and action-permission mappings.

```python
def test_secret_pattern_is_case_sensitive_and_whole_name():
    assert matches_secret_pattern("STRIPE_TEST_*", "STRIPE_TEST_KEY")
    assert not matches_secret_pattern("STRIPE_TEST_*", "stripe_test_key")
    assert not matches_secret_pattern("TEST_*", "STRIPE_TEST_KEY")


def test_reserved_permission_cannot_be_issued():
    with pytest.raises(PermissionValidationError) as exc:
        validate_grant(make_grant("secret:reveal"))
    assert exc.value.reason_code == "RESERVED_PERMISSION"
```

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_permissions.py -v
```

Expected: FAIL because `pushkey_permissions.py` does not exist.

- [ ] **Step 3: Implement permission constants and immutable grant models**

Add:

```python
PERMISSION_SET_VERSION = "agent-permissions-v1"
POLICY_VERSION = "2026-07-authorization-v1"
INTERFACES = frozenset({"cli", "local_api", "mcp"})
AUDIENCES = frozenset({"pushkey-local"})
ENVIRONMENTS = frozenset({"dev", "test", "staging", "prod", "all"})
SELECTOR_KEYS = (
    "project_ids",
    "secret_patterns",
    "environments",
    "path_identity_ids",
    "interfaces",
    "audiences",
)
```

Use frozen dataclasses or immutable tuples for validated grants. Implement the
action table from the specification. Do not use `fnmatch`, because character
classes must be rejected; translate only literal characters, `*`, and `?` into
an anchored internal regular expression.

- [ ] **Step 4: Run permission tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_permissions.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire packaging and compilation**

Add all new modules from this plan to `pyproject.toml` `py-modules` and to
`build_exe.py` hidden imports. This task adds `pushkey_permissions`; later tasks
append their modules.

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall pushkey_permissions.py
```

Expected: success.

- [ ] **Step 6: Commit the permission catalog**

```powershell
git add pushkey_permissions.py tests/test_permissions.py pyproject.toml build_exe.py
git commit -m "Add versioned agent permission catalog"
```

### Task 3: Replace The Agent Token Store With Schema v2

**Files:**
- Create: `pushkey_locking.py`
- Modify: `pushkey_agent_tokens.py`
- Modify: `pushkey_shared.py`
- Modify: `pushkey_vault.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_locking.py`
- Create: `tests/test_agent_token_v2.py`
- Modify: `tests/test_agent_tokens.py`
- Modify: `pyproject.toml`
- Modify: `build_exe.py`

- [ ] **Step 1: Fix test-path isolation with a failing regression**

Add a test asserting `_s.AGENT_TOKENS_FILE.parent == tmp_path`, then patch
`AGENT_TOKENS_FILE` in the autouse fixture. Verify no test accesses the user's
real `~/.pushkey/agent_tokens.enc`.

- [ ] **Step 2: Write failing cross-process lock tests**

Spawn two Python processes against one lock path. Assert the second process
times out while the first holds the lock and succeeds after release. Cover
cleanup after an exception and bounded timeout reason codes on Windows and
POSIX.

- [ ] **Step 3: Implement the bounded file lock**

Use `msvcrt.locking` on Windows and `fcntl.flock` on POSIX behind one context
manager. Initialize and lock one byte, retry with `time.monotonic()`, and never
delete another process's lock file. Add `pushkey_locking` to Python and
PyInstaller module lists. Refactor `pushkey_vault._cross_process_lock` to use
the shared implementation without changing the existing `.vault.lock` path or
public vault behavior.

- [ ] **Step 4: Write failing v2 issuance tests**

Cover required name/purpose, 128-character name maximum, 256-character purpose
maximum, `pushkey-local` audience, one-hour default expiry, 24-hour maximum,
900-second idle default, idle bounds of 60 through 3600,
25-use default, use bounds of 1 through 100, at least one grant, generated grant
IDs, Pushkey-generated timestamps, null parent lineage, trusted non-empty
`issuer_identity`, adapter-supplied `issuance_source` limited to `mcp`,
`local_api`, or `cli`, rejection of caller-supplied issuer fields, reserved
permission rejection, hash-only storage, wrapped key round trip, revocation
metadata retention, safe lifecycle listing, and no plaintext in serialized
storage.

- [ ] **Step 5: Write failing legacy migration tests**

Seed a real encrypted v1 store and assert:

- one immutable verified backup is created before rewrite;
- `read` becomes exactly three metadata grants;
- every migrated grant has exact wildcard project, secret, environment, and
  path selectors plus `interfaces=["mcp"]` and
  `audiences=["pushkey-local"]`;
- `write` and `inject` create warnings but no grants;
- migration expiry is one hour;
- authenticated-use migration sets `last_used_at` to migration time while bulk
  migration leaves it null;
- valid legacy `created` becomes `issued_at`, while invalid or missing
  `created` uses migration time;
- issuer, purpose, policy version, permission version, audience, use limits, and
  null lineage match the deterministic specification values, including exact
  `issuance_source="legacy-migration"` and null `revoked_at` and
  `revocation_reason`;
- write/inject-only tokens become `disabled_reissue_required`;
- disabled tokens cannot authenticate or unwrap the vault;
- warning order matches the specification;
- migration is idempotent;
- authenticated-use migration, bulk migration, issuance, and revocation all
  acquire the same adjacent token-store lock, and two synchronized processes
  cannot overwrite each other's migration or lifecycle mutation; and
- backup failure leaves the original byte-for-byte unchanged.

- [ ] **Step 6: Run focused token tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_locking.py tests\test_agent_tokens.py tests\test_agent_token_v2.py -v
```

Expected: failures for the missing v2 API and migration behavior.

- [ ] **Step 7: Implement the encrypted v2 store envelope**

Use:

```text
{
    "schema_version": 2,
    "tokens": list[TokenRecord],
    "authorization_journal": list[AuthorizationJournalEntry],
}
```

Add `issue_token`, `authenticate_credential`, `list_tokens`,
`revoke_token`, and `migrate_store`. Keep token plaintext only in the issuance
return value. Authentication returns token ID, vault key, and safe credential
metadata. It does not consume a use or update `last_used_at`.

Until Tasks 7 through 10 migrate every caller, retain deprecated adapters for
the current `create_token`, `authenticate_token`, coarse `list_tokens`, and
reasonless `revoke_token` signatures. The adapters delegate to v2 storage,
return the old shapes only to existing internal callers, and are covered by
compatibility tests. They are not used by new code.

- [ ] **Step 8: Implement restrictive migration and backup**

Use timezone-aware UTC and injectable `now` in tests. Create
`agent_tokens.enc.bak-v1-<UTC timestamp>` with exclusive creation, restrictive
permissions, file flush, parent flush where supported, and decrypt/parse
verification before replacing the source. Hold the same adjacent
cross-process token-store lock used by issuance and revocation across backup
verification, translation, and atomic replacement. Authenticated-use and bulk
migrations must use that same locked path.

- [ ] **Step 9: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_locking.py tests\test_agent_tokens.py tests\test_agent_token_v2.py -v
```

Expected: PASS.

- [ ] **Step 10: Record CP3 completion and commit**

Run the roadmap progress command and update the CP3 evidence row. Authorization
verified completion becomes 20%.

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git add pushkey_locking.py pushkey_agent_tokens.py pushkey_shared.py pushkey_vault.py tests/conftest.py tests/test_locking.py tests/test_agent_tokens.py tests/test_agent_token_v2.py pyproject.toml build_exe.py docs/PRODUCTION_READINESS_PLAN.md
git commit -m "Add constrained agent token v2 records"
```

### Task 4: Add Canonical Project And Path Identity

**Files:**
- Create: `pushkey_path_identity.py`
- Create: `tests/test_path_identity.py`
- Modify: `pushkey_vault.py`
- Modify: `pushkey_local_api.py`
- Modify: `pushkey.py`
- Modify: `tests/test_local_api.py`
- Modify: `pyproject.toml`
- Modify: `build_exe.py`

- [ ] **Step 1: Write failing registry migration tests**

Cover desktop name-keyed projects, local-API path-keyed projects, absolute-path
selection precedence, generated stable IDs, unambiguous `project_ids`
assignment migration, pending reauthorization, canonical collisions, encrypted
backup failure, and idempotency.

- [ ] **Step 2: Write failing hostile path tests**

Cover traversal, missing roots, symlinks, Windows reparse points and case
normalization where available, filesystem identity changes, Git remote as a
supporting signal only, and project moves without reauthorization.

- [ ] **Step 3: Write failing lifecycle tests**

Cover deletion tombstones, revoked path histories, re-registration receiving a
new project ID, and `reauthorize_project_path` preserving project IDs while
updating compatibility paths under CAS.

Enumerate every assignment source in failing tests:

- desktop initial project auto-match;
- desktop refresh auto-match;
- desktop assignment replacement and unassignment;
- desktop project removal;
- desktop vault/config import;
- local API assignment and unassignment;
- local API backup import; and
- the shared assignment transaction later called by MCP.

Each test asserts canonical secret `project_ids`, desktop compatibility `keys`,
and legacy secret path projections remain synchronized.

- [ ] **Step 4: Run focused path tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_identity.py -v
```

Expected: FAIL because the module does not exist.

- [ ] **Step 5: Implement the canonical authorization registry**

Implement:

```text
ensure_project_registry(config: dict, vault: dict, *, now=None) -> MigrationResult
resolve_path_identity(config: dict, project_id: str) -> PathIdentity
delete_project_identity(config: dict, vault: dict, project_id: str, *, now=None)
reauthorize_project_path(
    config: dict,
    vault: dict,
    project_id: str,
    new_path: str,
    *,
    now=None,
)
```

Store tombstones under
`config["authorization"]["projects_by_id"]`. Keep
`config["projects"]` and vault `projects` as compatibility projections;
authorization uses only `project_ids`.

- [ ] **Step 6: Add config revision and cross-process transaction support**

Add revision-aware config APIs without breaking existing callers:

```text
load_config_with_revision() -> tuple[dict, bytes | None]
save_config_if_revision(config: dict, expected_revision: bytes | None) -> bytes
```

The revision is the SHA-256 digest of the encrypted config bytes. Use this exact
lock hierarchy for every config/vault writer:

1. process-local `_VAULT_WRITE_LOCK`;
2. cross-process `_s.VAULT_DIR / ".vault.lock"`;
3. no agent-token lock while project-state files are being written.

Refactor public `save_vault`, `save_vault_with_key`, and `save_config` to acquire
that hierarchy. Add private already-locked CAS writers used only inside a
`project_state_transaction` context so the lock is never re-acquired. The
transaction loads both revisions, writes verified replacements, and rolls back
before releasing `.vault.lock`. Since every other vault/config writer uses the
same lock, rollback cannot overwrite a concurrent commit.

Inventory every direct `VAULT_FILE` write with `rg`. Route desktop recovery
reset, local API backup import, and any other direct vault replacement through
a shared `replace_vault_bytes` API, with a private already-locked variant for
transactions. Both variants use the same `.vault.lock` hierarchy. Add tests
proving each direct-replacement workflow blocks behind an active project-state
transaction and cannot bypass rollback protection.

Reject stale writes with a stable conflict error. Add tests proving two
processes cannot both commit from one config revision, the lock order does not
deadlock, and config/vault rollback restores both original byte streams after a
partial failure.

- [ ] **Step 7: Integrate registration, assignments, deletion, and moves**

Update local API and desktop project creation/deletion to maintain the registry.
Update desktop initial/refresh auto-match, replacement, unassignment, and
removal plus every local API assignment/unassignment path to maintain canonical
`project_ids`, desktop compatibility `keys`, and legacy path projections. Later
MCP assignment uses this same transaction service. Use vault CAS plus the new
config CAS, the shared lock hierarchy, verified backups, rollback, and
post-write checks. Do not add a new public move UI; expose only the internal
human operation and tests in this milestone.

- [ ] **Step 8: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_identity.py tests\test_local_api.py -v
```

Expected: PASS, with only the existing justified Windows symlink skip.

- [ ] **Step 9: Wire packaging and commit**

```powershell
git add pushkey_path_identity.py tests/test_path_identity.py pushkey_vault.py pushkey_local_api.py pushkey.py tests/test_local_api.py pyproject.toml build_exe.py
git commit -m "Add verified project identity registry"
```

### Task 5: Implement The Pure Policy Evaluator

**Files:**
- Create: `pushkey_policy.py`
- Create: `tests/test_policy.py`
- Modify: `pyproject.toml`
- Modify: `build_exe.py`

- [ ] **Step 1: Write failing decision tests**

Test each action mapping, all selector dimensions, no cross-grant selector
combination, multi-secret union, old/new environment checks, explicit wildcard
requirements, interface/audience mismatch, unknown schema and policy versions,
reserved reveal denial, unsupported obligations, and missing input. Also cover:

- `resource_contexts` must be a non-empty immutable collection;
- every context has `resource_type`, `resource_phase`, `secret_name`,
  `environment`, `project_id`, and `path_identity_id`;
- missing keys and null values in action-required dimensions deny;
- a concrete selector in a non-applicable dimension denies instead of being
  ignored, while an explicit `"*"` matches;
- vault and unfiltered policy/audit contexts use null resource dimensions;
- filtered policy/audit contexts populate every dimension used by the filter;
- list and health candidates are evaluated independently; and
- updates provide independently matching `current` and `requested` contexts.

```python
def test_inject_does_not_imply_reveal():
    decision = evaluate_authorization(
        request_for("secret.value.reveal"),
        credential_with_grant("secret:inject"),
    )
    assert decision.decision == "deny"
    assert decision.reason_code == "PERMISSION_NOT_GRANTED"
```

- [ ] **Step 2: Write failing metadata disclosure tests**

Prove unauthorized list entries are filtered; nested project IDs require both
permissions; notes, paths, history, and secret values are absent; and counts
include only authorized resources.

- [ ] **Step 3: Run policy tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_policy.py -v
```

Expected: FAIL because `pushkey_policy.py` does not exist.

- [ ] **Step 4: Implement immutable request and decision models**

Use pure data inputs:

```python
@dataclass(frozen=True)
class ResourceContext:
    resource_type: str
    resource_phase: Literal["current", "requested"]
    secret_name: str | None
    environment: str | None
    project_id: str | None
    path_identity_id: str | None


@dataclass(frozen=True)
class AuthorizationDecision:
    decision: Literal["allow", "deny", "requires_approval"]
    reason_code: str
    policy_version: str
    matched_grant_ids: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    approval_requirements: dict | None = None
    audit_context: dict = field(default_factory=dict)
```

Expose one deterministic evaluator entry point:

```text
evaluate_authorization(
    identity,
    credential_metadata,
    action,
    resource_contexts: tuple[ResourceContext, ...],
    interface,
    audience,
    request_context,
    executable_context=None,
) -> AuthorizationDecision
```

Do not import vault, token persistence, MCP, FastAPI, or filesystem mutation
code. Adapters and resolvers, not callers, construct concrete resource
contexts. Reject caller-supplied authorization patterns and any request context
containing secret values.

- [ ] **Step 5: Run policy tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_permissions.py tests\test_policy.py -v
```

Expected: PASS.

- [ ] **Step 6: Record CP4 completion and commit**

CP4 requires both Task 4 and Task 5 evidence. Update the roadmap only after
both focused suites pass. Authorization verified completion becomes 40%.

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git add pushkey_policy.py tests/test_policy.py pyproject.toml build_exe.py docs/PRODUCTION_READINESS_PLAN.md
git commit -m "Add deny by default authorization policy"
```

### Task 6: Add The Durable Authorization Journal

**Files:**
- Create: `pushkey_authorization.py`
- Create: `pushkey_audit.py`
- Create: `tests/test_authorization.py`
- Modify: `pushkey_agent_tokens.py`
- Modify: `pushkey_crypto.py`
- Modify: `pyproject.toml`
- Modify: `build_exe.py`

- [ ] **Step 1: Write failing authorization transaction tests**

Cover:

- authentication does not consume a use;
- allow reserves exactly one use and writes one `authorized` journal record;
- deny consumes no use;
- a stubbed evaluator result of `requires_approval` is converted to deny with
  `APPROVAL_SERVICE_UNAVAILABLE`, consumes no use, writes no authorized intent,
  and never starts protected work;
- successful empty metadata results consume one use;
- two separate Python processes released through one synchronization barrier
  cannot exceed a token with `max_uses=1`; exactly one reservation succeeds;
- revoked, expired, idle, and exhausted tokens deny;
- reservation and intent persist in one replacement;
- protected work never starts after persistence failure;
- success/failure updates are authoritative;
- outcome-write failure returns `OPERATION_OUTCOME_UNKNOWN`;
- audit projection failure returns the real outcome with
  `audit_projection_pending`; and
- retrying projection by operation ID does not rerun protected work.

- [ ] **Step 2: Run authorization tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_authorization.py -v
```

Expected: FAIL because the authorization service does not exist.

- [ ] **Step 3: Implement reserve, execute, and complete APIs**

Use a narrow interface:

```python
reservation = authorize_and_reserve(token_id, request, supported_obligations)
result = operation()
completion = complete_operation(reservation.operation_id, result_status)
```

Reload the token under the cross-process lock. Evaluate policy and atomically
replace the encrypted envelope with the incremented counter, updated
`last_used_at`, and journal intent. The completion journal is authoritative.

- [ ] **Step 4: Implement redacted audit projection**

`pushkey_audit.py` serializes only the approved audit schema and passes compact
JSON to a new strict `append_log_event` API that raises on persistence failure.
Keep the existing `log_event` wrapper for compatibility by having it call the
strict function and preserve its current best-effort exception suppression for
non-security callers. Add an idempotent operation-ID marker and projection retry
scan. Reject token plaintext, values, wrapped keys, passwords, and unredacted
output. Tests must force the strict append to fail and assert
`audit_projection_pending`.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_locking.py tests\test_authorization.py -v
```

Expected: PASS.

- [ ] **Step 6: Record CP5 completion and commit**

Authorization verified completion becomes 60%.

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git add pushkey_authorization.py pushkey_audit.py pushkey_agent_tokens.py pushkey_crypto.py tests/test_authorization.py pyproject.toml build_exe.py docs/PRODUCTION_READINESS_PLAN.md
git commit -m "Add atomic agent authorization journal"
```

### Task 7: Enforce Authorization In MCP

**Files:**
- Modify: `pushkey_mcp.py`
- Create: `tests/test_mcp_authorization.py`
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Write failing session identity tests**

Prove agent unlock stores token ID and vault key but not token plaintext or
coarse scopes. Prove master unlock creates a random process-local human session
ID and only that credential class can administer tokens.

- [ ] **Step 2: Write failing read-boundary tests**

Cover grant-filtered `list_keys`, `check_health`, and `list_projects`; safe
nested fields and counts; one use consumed per successful call; immediate
revocation; expiry and exhaustion after unlock; and `get_key` denial for every
agent-permissions-v1 token. After agent unlock, mutate a secret environment and
project assignment through a separate current vault/config writer; the next
metadata call must reload current resource state and must not authorize or
return data from the stale session snapshot.

- [ ] **Step 3: Write failing mutation tests**

Cover create, explicit update, rotate, backup update, backup promotion,
assignment, and injection. Verify `add_key(overwrite=True)` denies for agents,
old/new environments both match, stale vault revisions deny, project identity
must be active, all requested secrets match, and operation IDs are returned.

Define and test the replacement MCP signatures:

```python
create_agent_token(
    name: str,
    purpose: str,
    grants: list[dict],
    expires_in_seconds: int = 3600,
    idle_timeout_seconds: int = 900,
    max_uses: int = 25,
)
list_agent_tokens()
migrate_agent_tokens()
revoke_agent_token(token_id: str, reason: str)
update_key(
    name: str,
    provider: str | None = None,
    env: str | None = None,
    notes: str | None = None,
)
```

`update_key` preserves values and project assignments. Value replacement uses
the existing explicit rotation/backup workflows. All lifecycle mutation tools
require the caller-bound MCP human-master session. Remove the old coarse MCP
tool signature in this task, but retain a deprecated internal token-service
compatibility wrapper until the local API, CLI, and web callers migrate in
Tasks 8 through 10.

- [ ] **Step 4: Run MCP authorization tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mcp_authorization.py -v
```

Expected: FAIL because MCP still uses coarse session scopes.

- [ ] **Step 5: Replace coarse `_require_scope` with shared authorization**

Master-password calls retain current human behavior. Agent calls build named
authorization requests and execute through `pushkey_authorization`. Remove
agent reliance on session-cached scopes. Before building each agent request,
reload the current vault with the session vault key and reload the canonical
project registry under the shared read/transaction boundary. Resolve selectors
from that current state, not `_SESSION["vault"]`; convert every candidate or
affected resource into the complete `ResourceContext` contract before policy
evaluation, and carry the loaded vault revision into every mutation CAS. If
either current resource reload, context construction, or path identity
verification fails, deny before reserving a use or starting protected work.

- [ ] **Step 6: Enforce response schemas**

Return only allowed metadata. Keep injection results to names, counts, status,
warnings, operation ID, and audit status. Never return `NAME=value`, notes,
paths, history values, backup values, or secret plaintext to an agent metadata
call.

- [ ] **Step 7: Run MCP suites and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mcp.py tests\test_mcp_authorization.py -v
```

Expected: PASS. Existing master-password tests remain valid; legacy agent tests
are updated to the restrictive migration contract.

- [ ] **Step 8: Commit MCP enforcement**

```powershell
git add pushkey_mcp.py tests/test_mcp.py tests/test_mcp_authorization.py
git commit -m "Enforce agent authorization in MCP"
```

### Task 8: Bind Local API Human Sessions And Expose Token v2 Lifecycle

**Files:**
- Modify: `pushkey_local_api.py`
- Modify: `tests/test_local_api.py`

- [ ] **Step 1: Write failing caller-binding tests**

Create two bearer-session records directly in the test app. Prove that a
password unlock binds `human_master` and a vault-auth generation only to the
calling bearer. Another bearer cannot issue, migrate, or revoke tokens even
while process-global vault state is unlocked. Recovery authentication also
cannot administer tokens.

- [ ] **Step 2: Write failing v2 endpoint contract tests**

Define and test:

- `GET /api/agents`;
- `POST /api/agents` with name, purpose, grants, expiry, idle timeout, and max
  uses;
- `POST /api/agents/migrate`;
- `POST /api/agents/{token_id}/revoke` with a reason; and
- `GET /api/agents/options` with issuable permissions, safe project IDs,
  display names, active path identity IDs, environments, fixed MCP interface,
  and fixed `pushkey-local` audience; and
- stable safe lifecycle response fields and ordered warnings.

- [ ] **Step 3: Run focused API tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_local_api.py -k "agent or session" -v
```

Expected: failures because bearer dependencies return no caller record and the
v2 models do not exist.

- [ ] **Step 4: Return caller records from the bearer dependency**

Give every bearer a random session ID. Bind the current vault-auth generation
and credential class after password unlock. Lock/logout invalidates the
binding. Require a current `human_master` binding for all token administration.

- [ ] **Step 5: Add v2 lifecycle routes with temporary compatibility**

Use strict Pydantic request models and shared token services. Never include
token hashes or wrapped keys. Return token plaintext once on successful
issuance. Preserve the deprecated `POST /api/agents` coarse `scopes` request
body and existing `DELETE /api/agents/{token_id}` revoke route through Task 10
so the current web app remains functional between commits. Delegate both
compatibility paths to v2 services using the documented restrictive mapping,
emit stable deprecation warnings, and keep explicit compatibility tests.

- [ ] **Step 6: Run local API tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_local_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit local API lifecycle parity**

```powershell
git add pushkey_local_api.py tests/test_local_api.py
git commit -m "Bind agent lifecycle to local human sessions"
```

### Task 9: Add CLI Token v2 Lifecycle Commands

**Files:**
- Modify: `pushkey_cli.py`
- Create: `tests/test_cli_agents.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing parser and subprocess tests**

Specify:

```text
pushkey agent create --name NAME --purpose PURPOSE --grants FILE
                     [--expires-in 3600] [--idle-timeout 900] [--max-uses 25]
pushkey agent list [--json]
pushkey agent migrate [--json]
pushkey agent revoke TOKEN_ID --reason REASON
```

Tests mock `getpass`, assert master-password authentication, one command per
process invocation, JSON-safe output, stable exit codes, and no token plaintext
in `list`, `migrate`, or `revoke`. Token-administration commands must reject the
global `--password` option and `PUSHKEY_MASTER`; they accept the master password
only through the local `getpass` prompt.

- [ ] **Step 2: Run CLI tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli_agents.py -v
```

Expected: FAIL because the nested `agent` commands do not exist.

- [ ] **Step 3: Implement nested argparse commands**

Load the grants file as strict JSON and pass it through shared grant validation.
Create a random invocation ID after successful password authentication. Clear
local credential references in `finally`. Print the issued token once.

- [ ] **Step 4: Run CLI suites and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_cli_agents.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit CLI lifecycle parity**

```powershell
git add pushkey_cli.py tests/test_cli.py tests/test_cli_agents.py
git commit -m "Add agent token v2 CLI lifecycle"
```

### Task 10: Update The Local Web App Agent Controls

**Files:**
- Modify: `pushkey_agent_tokens.py`
- Modify: `tests/test_agent_tokens.py`
- Modify: `web-app/src/lib/api.ts`
- Modify: `web-app/src/components/agents-tab.tsx`
- Modify: `pushkey_web/out`
- Modify: `pushkey_web/_manifest.py`

- [ ] **Step 1: Update TypeScript contracts**

Replace coarse scopes with `AgentGrant`, `AgentIssueRequest`, and safe
`AgentToken` lifecycle fields. Add migrate and reasoned-revoke API methods.

- [ ] **Step 2: Replace the coarse scope form**

Add:

- required name and purpose;
- permission menu limited to issuable permissions;
- project, secret pattern, environment, path identity, interface, and audience
  selectors;
- expiry, idle timeout, and max-use controls within server limits;
- migration warnings and reissue status;
- expiry/use columns; and
- one-time token reveal.

Do not expose reserved permissions. Do not add approval, execution, or reveal
controls. Populate `project_ids` and active `path_identity_ids` from
`GET /api/agents/options`; use explicit `"*"` for both when the human chooses
all projects. Submit `interfaces=["mcp"]` and
`audiences=["pushkey-local"]` as fixed visible context, not user-editable
free-form values.

- [ ] **Step 3: Build the production web app**

```powershell
Set-Location web-app
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
```

Expected: Next.js build succeeds and integrity generation completes.

- [ ] **Step 4: Run API contract tests again**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_local_api.py -k agent -v
```

Expected: PASS.

- [ ] **Step 5: Remove all temporary token lifecycle compatibility**

After MCP, local API, CLI, and web callers all use v2 grants, delete the
deprecated internal `create_token`, `authenticate_token`, coarse `list_tokens`,
and reasonless `revoke_token` adapters and their compatibility tests. Remove
the deprecated local API coarse `scopes` POST body and DELETE revoke route, then
update endpoint tests to require only the v2 lifecycle contract. Run token,
MCP, local API, and CLI focused tests.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_tokens.py tests\test_agent_token_v2.py tests\test_mcp.py tests\test_mcp_authorization.py tests\test_local_api.py tests\test_cli.py tests\test_cli_agents.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the web lifecycle UI**

```powershell
git add pushkey_agent_tokens.py tests/test_agent_tokens.py web-app/src/lib/api.ts web-app/src/components/agents-tab.tsx pushkey_web/out pushkey_web/_manifest.py
git commit -m "Update agent token lifecycle controls"
```

### Task 11: Complete Cross-Interface And Adversarial Verification

**Files:**
- Modify: `tests/test_agent_token_v2.py`
- Modify: `tests/test_path_identity.py`
- Modify: `tests/test_policy.py`
- Modify: `tests/test_authorization.py`
- Modify: `tests/test_mcp_authorization.py`
- Modify: `tests/test_local_api.py`
- Modify: `tests/test_cli_agents.py`
- Modify: `SECURITY.md`
- Modify: `docs/mcp-setup.md`

- [ ] **Step 1: Add lifecycle parity fixtures**

Issue equivalent token requests through MCP master session, local API
human-master session, and CLI. Normalize transport wrappers and assert identical
safe metadata, grant summaries, defaults, warnings, migration state, and
revocation behavior.

- [ ] **Step 2: Add the hostile authorization matrix**

Cover malformed schemas, unknown actions, missing selectors, secret glob edge
cases, `"*"` mixed with concrete selector entries, unknown environments,
missing/empty resource contexts, null required context dimensions, concrete
selectors on non-applicable dimensions, stale vault revisions,
expired/idle/exhausted/revoked tokens, concurrent last-use races, concurrent
migration/lifecycle races, lock timeout, store corruption, audit projection
retry, moved projects, deleted tombstones, symlink/junction escape, and
unsupported obligations.

- [ ] **Step 3: Add explicit non-disclosure assertions**

Search serialized responses, logs, journal projections, exceptions, and test
artifacts for seeded token plaintext, wrapped keys, master passwords, active
values, backup values, and `NAME=value` strings.

- [ ] **Step 4: Run all authorization-focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_permissions.py tests\test_agent_tokens.py tests\test_agent_token_v2.py tests\test_path_identity.py tests\test_policy.py tests\test_locking.py tests\test_authorization.py tests\test_mcp.py tests\test_mcp_authorization.py tests\test_local_api.py tests\test_cli.py tests\test_cli_agents.py -v
```

Expected: PASS except the already justified Windows symlink skip when the host
cannot create symlinks.

- [ ] **Step 5: Update the security and MCP contracts**

Document granular permissions, non-issuable permissions, one-hour legacy grace,
reissue warnings, interface boundaries, use accounting, path identity,
operation outcome uncertainty, audit projection warnings, and the continued
plaintext-over-chat warning policy.

- [ ] **Step 6: Commit adversarial coverage**

```powershell
git add tests SECURITY.md docs/mcp-setup.md
git commit -m "Verify agent authorization boundaries"
```

### Task 12: Run CP6 And CP7 Phase Gates

**Files:**
- Modify: `docs/PRODUCTION_READINESS_PLAN.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/AGENTIC_VISION.md`

- [ ] **Step 1: Run Python static and dependency checks**

```powershell
Get-ChildItem -Path . -Filter 'pushkey*.py' -File | ForEach-Object {
    .\.venv\Scripts\python.exe -m py_compile $_.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
.\.venv\Scripts\python.exe -m compileall server
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: both pass.

- [ ] **Step 2: Run the complete Python suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --durations=30 --durations-min=0.1
```

Expected: all collected tests pass with only documented platform skips and no
new hidden warnings.

- [ ] **Step 3: Verify temporary files and processes**

```powershell
$retained = (Get-ChildItem .pytest_tmp -Force -ErrorAction SilentlyContinue | Measure-Object).Count
if ($retained -ne 0) { throw "pytest retained $retained entries" }
$testProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(python|pythonw|uvicorn).*' -and
    $_.CommandLine -match 'pytest|uvicorn|pushkey_local_api|--local-api-server'
}
if ($testProcesses) {
    $testProcesses | Select-Object ProcessId, Name, CommandLine
    throw "test-owned process remains"
}
```

Expected: no retained passing-test entries and no test-owned process remains.

- [ ] **Step 4: Build both frontend applications**

```powershell
Set-Location web
npm run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..\web-app
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run integrity
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run integrity
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
git diff --exit-code -- pushkey_web/out pushkey_web/_manifest.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: lint/builds pass, repeated integrity generation passes, and generated
web artifacts plus their trust-anchor manifest remain deterministic.

- [ ] **Step 5: Verify packaging includes every new module**

```powershell
.\.venv\Scripts\python.exe -c "import pushkey_permissions, pushkey_locking, pushkey_path_identity, pushkey_policy, pushkey_authorization, pushkey_audit"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$modules = @(
    "pushkey_permissions",
    "pushkey_locking",
    "pushkey_path_identity",
    "pushkey_policy",
    "pushkey_authorization",
    "pushkey_audit"
)
foreach ($module in $modules) {
    rg -n ('"' + $module + '"') pyproject.toml
    if ($LASTEXITCODE -ne 0) { throw "$module missing from pyproject.toml" }
    rg -n $module build_exe.py
    if ($LASTEXITCODE -ne 0) { throw "$module missing from build_exe.py" }
}
```

Expected: imports and packaging searches pass.

- [ ] **Step 6: Build and smoke-test packaged executables**

Run from a clean PyInstaller cache as required by the repository build policy:

```powershell
$workspace = (Resolve-Path .).Path
$targets = @("build", "dist", "Pushkey.spec") | ForEach-Object {
    [IO.Path]::GetFullPath((Join-Path $workspace $_))
}
if ($targets | Where-Object { -not $_.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar) }) {
    throw "build cleanup target escaped workspace"
}
Remove-Item -Recurse -Force -LiteralPath $targets[0] -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force -LiteralPath $targets[1] -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath $targets[2] -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe build_exe.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\dist\pushkey-cli.exe --help
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-Item .\dist\Pushkey.exe, .\dist\pushkey-cli.exe
```

Expected: both executables are built and the CLI help exits zero. Do not copy
artifacts to the desktop in this task.

- [ ] **Step 7: Perform the threat-model review**

Review the implemented data flow against every deny-by-default rule in the
specification. Record evidence for transcript exposure, selector bypass,
cross-process races, caller confusion, path moves, store corruption, audit
degradation, and secret-bearing errors.

- [ ] **Step 8: Update final percentages and evidence**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git status --short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Mark CP6 at 80% only after lifecycle parity and MCP enforcement pass. Mark CP7
and authorization verification at 100% only after every command in this task
passes. Record the exact production denominator and percentage without
rounding away incomplete items.

- [ ] **Step 9: Commit the verified checkpoint**

```powershell
git add docs/PRODUCTION_READINESS_PLAN.md docs/ARCHITECTURE.md docs/AGENTIC_VISION.md
git commit -m "Record verified agent authorization foundation"
```

- [ ] **Step 10: Verify final repository state**

```powershell
git status --short --branch
git log -12 --oneline --decorate
```

Expected: clean `feat/pushkey-app` branch with small checkpoint commits and no
unrelated files.

## Final Completion Report

After Task 12, report:

1. Work completed by CP2 through CP7.
2. Focused, integration, full-suite, build, and packaging evidence.
3. Repository branch, HEAD, and clean/dirty state.
4. Exact verified production checklist numerator, denominator, and percentage.
5. Authorization implementation and verification percentage.
6. Remaining Phase 1 and Phase 2 production blockers.
7. Deferred agentic work: `pushkey run`, approval persistence, provider
   brokers, sandboxing, remote agents, and advanced audit signing.
8. The next independently testable production-readiness action.
