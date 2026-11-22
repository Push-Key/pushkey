# Pushkey Local API v1

Status: Phase 1 contract for the local browser app.

The local API is a loopback-only adapter between `web-app/` and the local
encrypted vault. It is not a cloud API and must not be exposed to a network
interface.

## Boundary

- Bind address: `127.0.0.1` only.
- Readiness endpoint: `GET /healthz` is intentionally unauthenticated and
  returns only process readiness metadata.
- Application endpoints require `Authorization: Bearer <launch-token>`.
- The launch token is generated per local app launch and is not a persistent
  account credential.
- Vault operations that require plaintext secrets are available only after
  unlock and must keep responses as narrow as the UI requires.

## Client

The canonical TypeScript client is `web-app/src/lib/api.ts`. Every endpoint
used by that file must have a matching route in `pushkey_local_api.py`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Return lock state, vault presence, schema, key count, idle state, auth method, and write capability. |
| POST | `/api/bootstrap` | Exchange the one-time launch token from the URL fragment for an in-browser session token, then consume the launch token. |
| POST | `/api/logout` | Revoke the current browser session token and clear unlocked vault state. |
| POST | `/api/unlock` | Unlock with master password, recovery code or agent token. A master-password unlock also runs the one-time project store migration; a failing migration never blocks the unlock. |
| POST | `/api/lock` | Clear the in-memory unlocked session. |
| GET | `/api/keys` | List masked key summaries. |
| POST | `/api/keys` | Add a key [write]. An optional `connect` object (`project`, optional `file`, `var`, `confirmed`) also connects it to a registered project's env file [write and inject]. `overwrite=true` replaces the value the way a rotation does, keeps the key's connections and syncs them. |
| GET | `/api/keys/{name}` | Reveal one key's detail. |
| PATCH | `/api/keys/{name}` | Update key metadata. |
| DELETE | `/api/keys/{name}` | Delete a key. |
| POST | `/api/keys/{name}/rotate` | Rotate a key to a new value [write]; the response lists the connected files rewritten (`synced`), or for an agent token without the inject scope the connections not rewritten (`not_synced`). |
| POST | `/api/keys/{name}/backup` | Stage a backup key value. |
| POST | `/api/keys/{name}/promote` | Promote a staged backup value [write]; `synced` / `not_synced` as for rotate. |
| GET | `/api/projects` | List registered projects [read], with the keys connected to each and the connection count. |
| POST | `/api/projects` | Register a project path (master-password session only; the plan's project limit answers 402). |
| DELETE | `/api/projects` | Delete a project registration selected by query parameter, and every key's connections to it (master-password session only). |
| POST | `/api/projects/assign` | Connect keys to a project selected by query parameter [write], using the project's default file and the key name as variable; no file is written. An environment mismatch or browser-bundled name needs `confirmed`. |
| POST | `/api/projects/unassign` | Disconnect keys from a project selected by query parameter [write]. |
| POST | `/api/projects/inject` | Preview or write the project's connected variables [inject]; connected values are replaced, other variables are left alone, and explicit `keys` must be connected. |
| POST | `/api/connections/preview` | Preview a connection [read]: the confirmation line, what would change and what needs confirming. |
| POST | `/api/connections` | Connect a key to a variable in a registered project's env file and write it [write and inject]. |
| DELETE | `/api/connections` | Remove one connection, selected by key, project, file and variable in the body [write]. |
| GET | `/api/connections` | List connections with their state, optionally for one `key` and/or `project` [read]. |
| POST | `/api/connections/sync` | Rewrite connected variables with the keys' current values, optionally for one `key` and/or `project` [inject]. |
| GET | `/api/connections/suggest` | Suggest projects, files and variable names for a `key` [read]. |
| GET | `/api/connect/notice` | Read the one-time notice the project migration left [read]. |
| DELETE | `/api/connect/notice` | Dismiss that notice [write]. |
| GET | `/api/health` | Return vault health classification for the local dashboard. |
| GET | `/api/forecast` | Return upcoming rotation forecast. |
| GET | `/api/lifecycle/{name}` | Return lifecycle detail for one key. |
| GET | `/api/audit` | Return local audit events. |
| GET | `/api/agents` | List local agent tokens. |
| POST | `/api/agents` | Create a local agent token. |
| DELETE | `/api/agents/{token_id}` | Revoke a local agent token. |
| POST | `/api/backup/export` | Export encrypted backup blob. |
| POST | `/api/backup/import` | Import encrypted backup blob. |
| POST | `/api/recovery/add` | Add a recovery-code unlock slot. |
| POST | `/api/vault/rekey` | Rekey the vault using a recovery code. |

## Connect errors

The connection and project routes answer with `{"detail": "<code>"}`; the code is
stable, and `confirmation_required` also carries `"needs": [...]` (the confirmations
still missing).

| Status | Codes |
|---|---|
| 400 | `file_tracked_by_git`, `invalid_var`, `invalid_env_file`, and a refused project path (its reason text) |
| 402 | `project_limit` |
| 404 | `key_not_found`, `project_not_registered`, `connection_not_found` |
| 409 | `migration_pending`, `key_exists`, `project_exists`, `var_taken`, `confirmation_required`, `vault_changed` |
| 423 | `vault_unavailable` |
| 500 | `read_failed`, `backup_failed` |
| 503 | `config_unreadable`, `config_busy` |

A connection whose file could not be written is not an error: the result has
`written: false` and a `reason`, and the connection stays; `sync` retries it. Warnings
(`health_publication_failed`, `last_error_not_recorded`) come in the
`X-Pushkey-Warning` header.

## Compatibility

This contract is v1. Route removals, response-shape removals, and authentication
changes require a new contract version or a documented compatibility bridge.
