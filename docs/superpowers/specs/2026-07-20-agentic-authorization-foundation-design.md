# Pushkey Agentic Authorization Foundation Design

Date: 2026-07-20
Status: Approved for implementation planning

## Purpose

Pushkey will add an authorization foundation that lets agents use narrowly
approved secret capabilities without treating plaintext disclosure as ordinary
read access. The foundation must be shared by MCP, the local API, the CLI, and
the future controlled-execution service.

This work follows a foundation-first dual track:

- the existing production-readiness phases remain the launch authority;
- reusable agent authorization controls are added during local product
  hardening; and
- subprocess execution, approval persistence, provider brokers, sandboxing,
  and remote agent workflows remain outside the launch critical path.

## Current Baseline

The production roadmap currently contains 340 checklist items:

- 23 items are marked verified, for 6.8 percent checklist completion;
- Phase 0 is complete at 18 of 18 items;
- Phase 1 has no formally checked items, although some canonical architecture
  and cloud-license work exists and requires an evidence audit;
- Phase 3 has 5 of 18 items checked, primarily administrator authentication
  and password hardening; and
- one of thirteen phase gates is complete, for 7.7 percent phase-gate
  completion.

The existing agent-token code provides an estimated 20 to 25 percent of the
prototype functionality described here: token-prefixed identities, encrypted
token records, wrapped vault keys, coarse scopes, last-used tracking, and
revocation. None of the new authorization foundation is production-verified,
so its verified completion is 0 percent at the start of this work.

These two measurements must remain separate. Prototype coverage does not count
as verified roadmap completion.

## Goals

1. Replace coarse `read`, `write`, and `inject` checks with versioned,
   precisely defined permissions.
2. Require explicit authorization for plaintext disclosure.
3. Bind grants to resource selectors and approved interfaces.
4. Add token expiry, idle timeout, maximum-use, revocation, lineage, and
   purpose metadata.
5. Evaluate authorization through one deny-by-default policy contract.
6. Verify project and working-directory identity before path-constrained
   operations.
7. Reserve token uses atomically before protected operations.
8. Return structured decisions, obligations, approval requirements, and audit
   context without including secret values.
9. Migrate legacy scopes visibly and conservatively.
10. Make verified progress measurable through explicit evidence gates.

## Non-Goals

This milestone will not implement:

- `pushkey run` or child-process injection;
- persistent approval records or approval user interfaces;
- provider-brokered actions;
- operating-system sandboxing, containers, or micro-VMs;
- network egress enforcement;
- temporary provider credentials or canary credentials;
- team or remote approval workflows; or
- remote MCP transport.

The evaluator may return `requires_approval`, but approval-dependent operations
must be denied until an approval service can validate an exact approval
artifact.

## Architecture

### Permission catalog

`pushkey_permissions.py` will own permission names, semantic definitions,
permission-set versions, and legacy translations. It will have no transport or
vault dependency.

The first permission set is `agent-permissions-v1`.

| Permission | Meaning |
|---|---|
| `vault:metadata` | Read vault format and aggregate metadata, never secret names or values |
| `secret:metadata` | Read allowed secret names, providers, environments, tags, versions, and timestamps, never values |
| `secret:inject` | Place selected values into an approved destination without returning plaintext |
| `secret:execute` | Authorize future controlled execution with selected secrets, without disclosure |
| `secret:rotate` | Rotate an allowed secret through an approved workflow |
| `secret:create` | Create an allowed secret record |
| `secret:update` | Update allowed secret metadata or value through an approved input channel |
| `secret:delete` | Delete an allowed secret record; excluded from default agent profiles |
| `secret:reveal` | Permit plaintext disclosure only through an explicitly allowed channel and approval policy |
| `project:read` | Read metadata for selected registered projects |
| `policy:read` | Read effective non-secret policy metadata |
| `audit:read` | Read redacted audit records allowed by policy |
| `operation:approve` | Approve an exact future operation plan; not active in this milestone |

`secret:inject` and `secret:execute` never imply `secret:reveal`. Unknown
permissions are denied.

### Grant model

A token contains one or more grants. Each grant has one permission and explicit
selectors:

```json
{
  "grant_id": "grant_01",
  "permission": "secret:inject",
  "selectors": {
    "project_ids": ["project_billing_api"],
    "secret_patterns": ["STRIPE_TEST_*"],
    "environments": ["development"],
    "path_identity_ids": ["path_01"],
    "interfaces": ["mcp"],
    "audiences": ["pushkey-local"]
  }
}
```

Every selector array is required. An unrestricted dimension must use an
explicit `"*"` entry. Missing, empty, malformed, or unsupported selectors deny
the grant. Secret patterns use a documented glob subset rather than regular
expressions supplied by users.

The interface is policy input and a grant constraint. It is not encoded by
creating separate scope names such as `reveal_to:mcp`. Initial interface names
are `cli`, `local_api`, and `mcp`.

Selector matching uses these rules:

- every non-secret selector dimension is conjunctive within one grant;
- every requested secret must be matched completely by at least one grant;
- separate grants may cover separate secrets in a multi-secret request, but
  selector dimensions from different grants may never be combined to authorize
  one secret;
- project IDs, path identity IDs, environments, interfaces, and audiences use
  case-sensitive exact matching;
- secret-name matching is case-sensitive on every platform and matches the
  entire name;
- secret patterns support only literal characters, `*` for zero or more
  characters, and `?` for exactly one character;
- character classes, alternation, and caller-supplied regular expressions are
  rejected; and
- duplicate or conflicting grants do not widen access beyond the union of
  independently complete grant matches.

Each protected adapter operation has one action identifier and permission:

| Current or reserved operation | Action identifier | Required permission |
|---|---|---|
| Vault aggregate status | `vault.metadata.read` | `vault:metadata` |
| `list_keys`, `check_health` | `secret.metadata.list` | `secret:metadata` |
| `inject_env` | `secret.value.inject` | `secret:inject` |
| Future controlled execution | `secret.execution.request` | `secret:execute` |
| `rotate_key`, `rotate_to_backup` | `secret.rotate` | `secret:rotate` |
| `add_key` when the name is absent | `secret.create` | `secret:create` |
| Secret metadata edits | `secret.metadata.update` | `secret:update` |
| `set_backup_key` and value replacement | `secret.value.update` | `secret:update` |
| Future secret deletion | `secret.delete` | `secret:delete` |
| `get_key` | `secret.value.reveal` | `secret:reveal` |
| `list_projects` | `project.metadata.read` | `project:read` |
| `assign_key` | `project.secret.assign` | `secret:update` |
| Effective policy metadata | `policy.metadata.read` | `policy:read` |
| Redacted audit listing | `audit.redacted.read` | `audit:read` |
| Future operation approval | `operation.approve` | `operation:approve` |

Unknown action identifiers deny. Adapters may not substitute a less privileged
action for a more privileged operation.

Agent-token calls to `add_key(overwrite=True)` are denied. Agent callers use an
explicit update operation instead. Human master-password workflows may retain
the compatibility flag, but they do not define agent authorization semantics.

An explicit update is evaluated against both the pre-state and requested
post-state. An environment change must match the grant in both environments.
Value and metadata updates preserve project assignments unless a separate
`project.secret.assign` operation is authorized. The implementation uses the
existing vault revision/CAS mechanism so a stale decision cannot overwrite a
record changed after authorization.

Selector applicability is action-specific:

| Action family | Selectors that must match |
|---|---|
| Vault aggregate | interface and audience; all resource selectors must be explicit `"*"` |
| Secret metadata/health | every returned secret name and its stored environment; project and path apply when the request is project-filtered |
| Secret create | requested secret name and environment; project/path apply only when creation also assigns a project |
| Secret update/rotate/reveal | existing secret name and stored environment; project/path apply when the request is project-bound |
| Inject | every secret name and stored environment plus the registered project ID and active path identity ID |
| Project list | each returned project ID; path identity applies when path metadata is returned |
| Project assignment | secret name and environment plus project ID and active path identity ID |
| Audit/policy metadata | interface and audience plus any resource identifiers used to filter the request |

For list and health operations, unauthorized entries are filtered rather than
causing the whole request to fail. For mutations and injection, every affected
resource must match or the entire operation is denied. A stored secret
environment of `all` matches only a grant environment of `all` or `"*"`;
environment names otherwise use exact matching.

Agent metadata responses use a fixed disclosure policy:

- `secret:metadata` may return name, provider, environment, health status,
  version identifier, and creation/rotation timestamps;
- it never returns plaintext values, backup values, history values, notes,
  project paths, or arbitrary free-form metadata;
- `project:read` may return project ID, display name, and lifecycle state;
- full canonical paths and path identity history are not returned to agent
  metadata callers;
- secret names nested in a project response require both `project:read` for the
  project and `secret:metadata` for each secret;
- project identifiers nested in a secret response require both permissions;
  and
- counts and aggregates include only resources authorized for that response.

Adapters return omitted fields rather than null placeholders for unauthorized
cross-resource data. These response schemas are contract fixtures in CP6.

### Agent-token schema v2

`pushkey_agent_tokens.py` will own credential issuance, encrypted persistence,
lookup, migration, and revocation. A v2 token record includes:

```json
{
  "schema_version": 2,
  "token_id": "at_123",
  "token_hash": "sha256...",
  "wrapped_vault_key": "v2:...",
  "name": "deploy-bot",
  "purpose": "Run development deployment checks",
  "issuer_identity": "local-human-session",
  "issuance_source": "local_api",
  "parent_token_id": null,
  "audience": "pushkey-local",
  "permission_set_version": "agent-permissions-v1",
  "policy_version_at_issuance": "2026-07-authorization-v1",
  "grants": [],
  "issued_at": "2026-07-20T18:00:00Z",
  "expires_at": "2026-07-21T18:00:00Z",
  "idle_timeout_seconds": 1800,
  "max_uses": 25,
  "uses_reserved": 0,
  "last_used_at": null,
  "revoked_at": null,
  "revocation_reason": null,
  "migration_state": null
}
```

Timestamps use timezone-aware UTC. Token plaintext is shown once and is never
persisted. The stored hash and wrapped vault key behavior remains encrypted at
rest.

The first implementation does not permit agent tokens to issue child tokens.
`parent_token_id` remains null but is present to make lineage explicit.

Initial issuance policy is:

- `name` and `purpose` are required non-empty strings of at most 128 and 256
  characters respectively;
- `audience` is required and must be `pushkey-local`;
- `expires_at` is required, defaults to one hour after issuance, and may not
  exceed 24 hours after issuance;
- `idle_timeout_seconds` defaults to 900 and must be between 60 and 3600;
- `max_uses` defaults to 25 and must be between 1 and 100;
- at least one valid grant is required;
- grant IDs are generated by Pushkey and are unique within the token;
- all timestamps are computed by Pushkey rather than accepted from the caller;
- only a local human session authenticated with the master password may issue
  or reissue a token; and
- `parent_token_id` is always null in this permission-set version.

The issuable permissions in `agent-permissions-v1` are `vault:metadata`,
`secret:metadata`, `secret:inject`, `secret:rotate`, `secret:create`,
`secret:update`, `project:read`, `policy:read`, and `audit:read`.
`secret:execute`, `secret:delete`, `secret:reveal`, and `operation:approve` are
reserved and non-issuable until their execution, deletion, disclosure-approval,
and approval workflows are implemented. Unknown and reserved permissions fail
issuance rather than being stored as inactive grants.

### Policy evaluator

`pushkey_policy.py` will be pure and deterministic. It receives named resource
metadata, never secret values:

```text
evaluate_authorization(
    identity,
    credential_metadata,
    action,
    project_id,
    canonical_path_identity,
    environment,
    secret_selectors,
    interface,
    audience,
    request_context,
    executable_context=None,
)
```

It returns:

```json
{
  "decision": "allow",
  "reason_code": "AUTHORIZED",
  "policy_version": "2026-07-authorization-v1",
  "matched_grants": [],
  "obligations": [
    "DO_NOT_RETURN_SECRET_VALUE",
    "RESERVE_TOKEN_USE",
    "RECORD_AUDIT_EVENT"
  ],
  "approval_requirements": null,
  "audit_context": {}
}
```

Valid decisions are `allow`, `deny`, and `requires_approval`. Reason codes are
stable machine-readable identifiers. Unknown obligations are not ignored; an
interface that cannot enforce every returned obligation must deny the
operation.

The evaluator contract supports a future plaintext reveal decision of
`requires_approval` when the grant and channel otherwise match. The v1
permission set cannot issue that grant. If a malformed, manually altered, or
future-version record requests it under the v1 permission set, authorization
denies it. When a later permission set makes reveal issuable, the authorization
service must still convert `requires_approval` to
`APPROVAL_SERVICE_UNAVAILABLE` until a valid approval service is present.

### Path identity resolver

`pushkey_path_identity.py` will resolve and verify project roots before policy
evaluation. The canonical identity registry is stored separately from the
existing compatibility project dictionary:

```json
{
  "authorization": {
    "schema_version": 1,
    "projects_by_id": {
      "project_01": {
        "project_id": "project_01",
        "name": "billing-api",
        "state": "active",
        "active_path_identity_id": "path_01",
        "path_identities": [
          {
            "path_identity_id": "path_01",
            "canonical_root": "C:\\repos\\billing-api",
            "device_fingerprint": "device hash",
            "filesystem_device": 123,
            "filesystem_inode": 456,
            "repository_root": "C:\\repos\\billing-api",
            "repository_fingerprint": "sha256...",
            "remote_origin_fingerprint": "sha256...",
            "authorized_at": "2026-07-20T18:00:00Z",
            "revoked_at": null,
            "state": "active"
          }
        ]
      }
    },
    "compatibility_project_index": {
      "billing-api": "project_01"
    }
  },
  "projects": {}
}
```

The project and path identity IDs are random Pushkey-generated identifiers.
They remain stable across display-name changes. New project registration
creates both IDs after path verification and adds an index entry for the
existing desktop/local-API project key. Each secret record gains a canonical
`project_ids` list. Its existing path-based `projects` list remains temporarily
as a compatibility projection and is not used for agent authorization.

Existing project records receive IDs the first time the config migration can
resolve their configured path on the current device. Existing secret
assignments are converted to project IDs only when their paths resolve
unambiguously through the compatibility index. Ambiguous assignments remain
unmapped and cannot satisfy an agent grant. This migration does not grant a
legacy token access because legacy write and inject scopes are not translated
into active grants.

Existing project path discovery is deterministic:

1. use `metadata.path` when it is an absolute path;
2. otherwise use the existing dictionary key only when that key is an absolute
   path;
3. canonicalize the selected path with strict existence checks;
4. mark the project `pending_reauthorization` when neither source produces a
   valid local directory; and
5. abort without merging records if two entries resolve to the same canonical
   root with different project IDs.

The config migration creates and verifies a recoverable encrypted config backup
before rewriting project metadata.

The existing `pushkey_tiers.get_machine_fingerprint()` supplies the initial
device binding. Filesystem device/inode values are recorded where the platform
provides stable values. Repository and remote fingerprints are supporting
signals and never replace filesystem and device checks by themselves.

A missing project is marked `missing`. A canonical root or filesystem identity
change is marked `moved` and denies path-constrained access. A local human must
reauthorize the new root, which creates a new path identity ID while preserving
the project ID and retaining the prior identity as revoked history.

Deleting a project sets the project state to `deleted`, revokes every path
identity, retains its `projects_by_id` tombstone and identity history, removes
its compatibility index entry, and removes the project ID and compatibility
path from active secret assignments. Re-registering the same display name or
filesystem path creates a new project ID. Old grants therefore remain denied
and cannot reactivate implicitly.

A project move is an explicit `reauthorize_project_path` human operation. It:

1. requires the caller-bound master-password session;
2. acquires the cross-process project/config/vault lock;
3. loads config and vault revisions and verifies the current active identity;
4. resolves the new path and rejects collisions;
5. revokes the old path identity and creates a new active identity;
6. updates the compatibility project index and path projection;
7. preserves canonical `project_ids` assignments while updating legacy path
   assignments; and
8. writes config and vault with backups, CAS checks, rollback on partial
   failure, and post-write verification before releasing the lock.

A path identity includes:

- a stable internal identity ID;
- registered project ID;
- normalized canonical root;
- platform normalization metadata;
- repository fingerprint when available;
- Git remote identity when configured; and
- device identity.

The resolver must reject traversal, symbolic-link or junction escapes, root
mismatches, missing paths, failed canonicalization, unsupported path forms, and
project moves that have not been reauthorized. Windows comparisons must account
for case-insensitive paths without weakening identity checks.

Future execution code must revalidate path identity at the point of use and
must not rely only on an earlier string comparison.

### Stateful authorization service

`pushkey_authorization.py` will coordinate token state without placing stateful
behavior in the policy evaluator:

```text
resolve verified resource identities
-> acquire the cross-process token-store lock
-> reload the token record
-> evaluate current revocation, expiry, idle, grant, and selector state
-> atomically reserve one use
-> persist the reservation and authorized operation intent
-> release the lock
-> perform the protected operation
-> record success or failure against the operation intent
```

A reserved use remains consumed if the operation fails. This prevents retries
and concurrent failures from bypassing `max_uses`. The operation outcome is
recorded separately.

The encrypted token store will use an adjacent lock file plus atomic
replacement. Lock acquisition has a bounded timeout. Lock timeout, persistence
failure, or unreadable token state denies the operation. The implementation
must work across separate local CLI, MCP, and local API processes.

The encrypted store envelope contains both token records and an authorization
journal. Every successfully authorized agent operation, including a metadata
read, receives an operation ID. Token use reservation and creation of the
corresponding `authorized` journal record occur in one in-memory mutation and
one atomic file replacement while the same lock is held. They cannot be
persisted separately.

Before any protected operation begins, the authorization service durably
records an `authorized` operation intent with the token-use reservation and
updates `last_used_at`. If that write fails, the operation does not begin.
After execution, the same operation record is updated to `succeeded` or
`failed` under the token-store lock. That journal update is the authoritative
outcome record. A corresponding audit-log event is an idempotent projection
keyed by operation ID.

If the outcome update fails after an irreversible operation, Pushkey returns
`OPERATION_OUTCOME_UNKNOWN`, does not retry automatically, and leaves the
durable `authorized` intent for recovery and incident review. This avoids
falsely reporting failure or success while ensuring the operation was never
performed without a durable security record.

If the authoritative outcome update succeeds but the audit-log projection
fails, Pushkey returns the real operation outcome with
`audit_projection_pending: true` and the operation ID. The next authorization
service startup or operation retries that projection idempotently. Callers must
not retry the protected operation in response to an audit projection warning.

Authentication, unlock, and denied authorization requests do not consume a
use. A successfully authorized list or health request consumes one use even
when filtering produces an empty result. Metadata-read journal and persistence
failures follow the same fail-closed behavior as mutations.

### Interface adapters

MCP is the only interface that accepts an agent token for protected vault
operations in this milestone. On successful token unlock it stores the token ID
and decrypted in-memory vault key, not the token plaintext. Every later
operation reloads current token state by token ID through the authorization
service, so revocation, expiry, idle timeout, and exhaustion take effect without
another unlock.

The local API and CLI integrate the v2 issuance, listing, migration-status, and
revocation services through a local master-password-authenticated human
session. They do not accept agent tokens for protected vault operations in this
milestone. Agent-authenticated local API sessions and general CLI agent-token
authentication require separate interface contracts before they can be
advertised.

A master-password-authenticated human session is caller-bound:

- MCP creates a random process-local human session ID after a successful master
  password unlock; token lifecycle calls require that exact MCP session;
- each CLI token lifecycle command authenticates with `getpass`, creates a
  process-local invocation ID, completes one command, and clears the credential
  state; and
- the local API assigns every bearer session a random session ID. A successful
  password unlock binds a new vault-authentication generation and
  `human_master` credential class to only the bearer session that submitted the
  password.

The local API must change its authentication dependency to return the caller's
bearer-session record. Token issuance, migration, and revocation require that
record to contain the current vault-authentication generation and
`human_master` class. Process-global decrypted vault state may support the
single-user UI, but it does not confer token-administration authority on another
bearer session. Recovery-code and agent-token sessions cannot administer
tokens. Lock and logout invalidate the caller binding.

Transport-specific code may parse requests and format responses, but it may not
define independent permission semantics. Cross-interface parity tests apply to
the token lifecycle operations common to MCP, local API, and CLI. Protected
agent-operation parity applies to MCP until another interface explicitly adopts
the credential contract.

The MCP `get_key` tool will require `secret:reveal`, an `mcp` interface match,
and a valid approval artifact. Normal and migrated agent tokens therefore
cannot reveal plaintext through MCP during this milestone.

The MCP `inject_env` response must contain names, counts, status, warnings, and
audit identifiers only. It must not return `NAME=value` lines.

Master-password sessions remain a separate local human credential class.
Their existing behavior is not silently assigned to agent tokens. The security
documentation continues to discourage sending master passwords through MCP.

## Deny-By-Default Rules

The authorization service denies protected operations for:

- unknown permission or permission-set version;
- unknown token schema;
- malformed or missing policy input;
- unsupported or missing selector dimensions;
- unresolved or mismatched project/path identity;
- failed symlink or junction validation;
- audience or interface mismatch;
- expired, idle, exhausted, revoked, or unknown tokens;
- unavailable evaluator or token store;
- failed token lock or atomic reservation;
- unsupported obligations;
- required approval without a valid approval service and artifact;
- legacy translation failure; and
- mandatory audit persistence failure.

Error responses expose stable reason codes and safe operator guidance. They do
not expose token hashes, wrapped keys, secret values, policy internals useful
for bypass, or sensitive filesystem details.

## Legacy Migration

Before the first v2 rewrite, Pushkey creates one immutable sibling backup named
`agent_tokens.enc.bak-v1-<UTC timestamp>`. Backup creation uses exclusive
creation, restrictive permissions, file flush, and parent-directory flush where
supported. Migration aborts without changing the source if backup creation or
verification fails.

Legacy records without `schema_version: 2` are translated on authenticated use
or explicit migration:

| Legacy scope | Granular translation |
|---|---|
| `read` | `vault:metadata`, `secret:metadata`, and `project:read` |
| `write` | No grants; token reissue required |
| `inject` | No grants; token reissue required |

Legacy `read` never translates to `secret:reveal`. Legacy mutation access is
not preserved because the old token contains no defensible resource selectors.
The metadata translation uses explicit wildcard selectors for project,
secret-name, environment, and path dimensions, the `mcp` interface, and the
`pushkey-local` audience. This is narrower than legacy `read` because it removes
plaintext disclosure and applies only through the existing MCP agent-token
interface. Injection and mutation remain denied until human-authorized reissue.

Required v2 fields absent from a legacy record receive these deterministic
values:

- `issued_at`: the valid legacy `created` timestamp, otherwise migration time;
- `expires_at`: migration time plus one hour;
- `idle_timeout_seconds`: 900;
- `max_uses`: 25;
- `uses_reserved`: 0;
- `last_used_at`: migration time for authenticated-use migration, otherwise
  null for explicit bulk migration;
- `purpose`: `Migrated legacy token: <legacy name>`;
- `issuer_identity`: `legacy-import`;
- `issuance_source`: `legacy-migration`;
- `audience`: `pushkey-local`;
- `permission_set_version`: `agent-permissions-v1`;
- `policy_version_at_issuance`: `2026-07-authorization-v1`; and
- `parent_token_id`, `revoked_at`, and `revocation_reason`: null.

A token with legacy `read` receives three generated grants for
`vault:metadata`, `secret:metadata`, and `project:read`. A legacy token with no
`read` scope receives no grants, is marked `disabled_reissue_required`, and
cannot authenticate or unwrap the vault through an adapter. It remains visible
to human token-listing and revocation workflows until it expires or is revoked.

Translated records include visible migration state and warning codes:

- `legacy_scope_translated`;
- `legacy_read_mapped_to_metadata`;
- `legacy_write_reissue_required`;
- `legacy_inject_reissue_required`; and
- `reissue_required_for_reveal`.

Warnings are returned in the order above, with inapplicable entries omitted and
no duplicates. Token lifecycle listings use a shared response fixture containing
only token ID, name, purpose, schema version, status, expiry, last use, reserved
uses, maximum uses, grant summaries, migration state, and ordered warnings.
They never return token hashes or wrapped vault keys.

Migration is idempotent, creates a recoverable backup, and never silently
widens access. Operators can list tokens requiring reissue.

## Audit Requirements

Authorization audit events contain:

- event ID and timestamp;
- token ID, issuer, and lineage metadata;
- action and selected resource identifiers;
- interface and audience;
- policy and permission-set versions;
- decision and reason code;
- matched grant identifiers;
- obligations;
- use reservation number;
- operation outcome; and
- migration warnings.

Audit events never contain token plaintext, secret plaintext, wrapped vault
keys, master passwords, or unredacted command output.

Tamper-evident hash chaining and signed export remain later work, but the event
shape must support those additions without changing authorization semantics.

## Verification

Authorization work is `Verified` only when all applicable evidence exists:

- permission-semantic unit tests;
- deny-by-default negative tests;
- token migration and backup tests;
- expiry, idle-timeout, exhaustion, and revoked-token tests;
- concurrent use-reservation tests across processes;
- path traversal, symlink, junction, case, and project-move tests;
- cross-interface parity tests;
- tests proving inject and execute never imply reveal;
- tests proving unsupported obligations deny;
- approval-unavailable tests;
- audit event schema and redaction tests;
- threat-model review;
- full Python regression suite; and
- affected frontend or extension builds and tests.

No completion credit is granted solely because code exists.

## Checkpoints

### CP1: Phase 1 health sidecar contract

This is an independent prerequisite, not an authorization component. It
requires a separate approved design defining the exact schema envelope,
backward compatibility for the current top-level secret-name map, producer
validation, and extension migration behavior. This authorization specification
does not provide implementation authority for the health contract.

Estimate: 1 to 2 engineering days.

### CP2: Agentic specification and roadmap

- add the approved Agentic Vision as a dedicated document;
- add its dependency map and launch boundaries to the production roadmap;
- define the permission and selector contracts; and
- add evidence-based completion reporting.

Estimate: 1 to 2 engineering days.

### CP3: Token v2 and restrictive migration

- implement the v2 record and grant schemas;
- add issuance constraints and security metadata;
- add restrictive legacy translation, backup, warnings, and reissue status; and
- add focused token tests.

Estimate: 2 to 3 engineering days.

### CP4: Policy and path identity

- implement the pure policy evaluator;
- implement canonical project/path identity;
- add obligations and approval requirement results; and
- add fail-closed and hostile-input tests.

Estimate: 3 to 5 engineering days.

### CP5: Stateful authorization

- add cross-process locking and atomic use reservation;
- enforce revocation, expiry, idle timeout, and maximum use;
- record operation outcomes and audit context; and
- add concurrency and storage-failure tests.

Estimate: 2 to 4 engineering days.

### CP6: Interface enforcement

- route MCP protected operations through the shared authorization service;
- route MCP, local API, and CLI token lifecycle validation through the shared
  credential and permission services;
- remove plaintext reveal from legacy `read`;
- remove values from injection responses; and
- add CLI commands for v2 token issuance, listing, migration status, and
  revocation;
- update the local API and web app for the same v2 lifecycle operations; and
- add lifecycle parity tests across MCP, local API, and CLI.

Estimate: 3 to 5 engineering days.

### CP7: Adversarial phase verification

- run the hostile path and policy matrix;
- verify migration and operator messaging;
- update security and compatibility documentation; and
- run the full regression and build matrix.

Estimate: 2 to 4 engineering days.

The complete foundation is estimated at 14 to 25 engineering days, or about
three to five weeks for one experienced engineer. It does not include the
future controlled-execution or approval-persistence milestones.

## Progress Reporting

Every roadmap task uses one of these evidence states:

| State | Meaning | Completion credit |
|---|---|---:|
| Not started | No accepted design or implementation | 0 percent |
| Designed | Approved specification exists | 25 percent |
| Implemented | Code exists and focused tests pass | 50 percent |
| Verified | Adversarial, integration, and phase-gate evidence passes | 100 percent |
| Blocked | External dependency or unresolved decision | Retains last proven credit |

The main production percentage remains the binary checked-item result:

```text
verified checked items / total roadmap items
```

The report records the roadmap revision and denominator. When roadmap scope
changes, it shows both the prior and new denominator plus the scope delta.
Post-launch advanced agent features use a separate denominator and never reduce
the production-launch percentage. Agent authorization tasks added to existing
production hardening are counted in the production denominator only when they
are launch requirements.

Weighted engineering progress may be reported separately using the evidence
states above. It must never replace or be presented as the verified production
percentage.

Each checkpoint report includes:

- work completed;
- validation evidence;
- repository state;
- verified production percentage;
- weighted engineering percentage;
- current-phase percentage;
- agentic-foundation percentage;
- outstanding issues and blockers; and
- the next independently testable action.

## Roadmap Integration

The complete Agentic Vision will live in `docs/AGENTIC_VISION.md`. The main
production roadmap will contain a concise agentic-track section with:

- the product and security position;
- dependencies on production phases;
- the seven foundation checkpoints;
- deferred execution and advanced-agent milestones;
- completion metrics; and
- an explicit statement that advanced agent features do not delay the
  production launch.

The immediate execution order is:

1. complete CP1, the Phase 1 health sidecar contract;
2. complete CP2, the Agentic Vision and roadmap integration;
3. implement CP3 through CP6 using test-driven development; and
4. complete CP7 before marking the authorization foundation verified.
