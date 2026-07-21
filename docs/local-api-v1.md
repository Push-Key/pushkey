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
| POST | `/api/unlock` | Unlock with master password or recovery code. |
| POST | `/api/lock` | Clear the in-memory unlocked session. |
| GET | `/api/keys` | List masked key summaries. |
| POST | `/api/keys` | Add a key. |
| GET | `/api/keys/{name}` | Reveal one key's detail. |
| PATCH | `/api/keys/{name}` | Update key metadata. |
| DELETE | `/api/keys/{name}` | Delete a key. |
| POST | `/api/keys/{name}/rotate` | Rotate a key to a new value. |
| POST | `/api/keys/{name}/backup` | Stage a backup key value. |
| POST | `/api/keys/{name}/promote` | Promote a staged backup value. |
| GET | `/api/projects` | List project registrations. |
| POST | `/api/projects` | Register a project path. |
| DELETE | `/api/projects` | Delete a project registration selected by query parameter. |
| POST | `/api/projects/assign` | Assign keys to a project selected by query parameter. |
| POST | `/api/projects/unassign` | Unassign keys from a project selected by query parameter. |
| POST | `/api/projects/inject` | Preview or write project `.env` injection. |
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

## Compatibility

This contract is v1. Route removals, response-shape removals, and authentication
changes require a new contract version or a documented compatibility bridge.
