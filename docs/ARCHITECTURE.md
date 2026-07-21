# Pushkey Architecture

Status: canonical architecture for the production-readiness program.

## Launch scope decisions

- Primary client: CLI plus local web app.
- Legacy Tk desktop: supported maintenance client for the initial release, but
  new product workflows should land in the CLI/local web app first.
- Initial release scope: individual, local-first vault management with optional
  zero-knowledge cloud sync after durable storage lands.
- Deferred scope: team collaboration, SSO, GitHub webhooks, automated provider
  rotation, remote MCP, and provider brokers.
- Supported Python: 3.12 for the verified release baseline.
- Supported Node/npm: Node 24 and npm 11 for verified frontend builds.
- Claimed launch platforms: Windows first, with macOS and Linux only after CI,
  packaging, and install tests cover them.
- Repository boundary: public/open-core export must be generated from an
  allowlist; commercial cloud/admin code remains private until an explicit
  release-boundary decision changes that.

## Component ownership

| Component | Owner and responsibility | Trust boundary |
|---|---|---|
| `pushkey_crypto.py`, `pushkey_vault.py` | Vault formats, key derivation, local encryption, migration | Plaintext secrets remain in the local process |
| `pushkey_cli.py` + `web-app/` | Primary local client and browser UI | Browser talks only to the loopback local API |
| `pushkey_local_api.py` | Authenticated loopback adapter over local vault operations | Never exposed as the cloud service |
| `pushkey_tiers.py` | Device identity, encrypted local entitlement cache, activation client | Server responses override client claims |
| `pushkey_cloud_api.py` | Canonical cloud sync, account, license, device, CRM, portal, and admin API | Receives encrypted vault blobs and account/license metadata, never vault plaintext |
| `web/` | Public site, portal, and cloud administration UI | Uses only documented canonical cloud APIs |
| `server/` | Archived legacy activation implementation | Must not contain deployable service code |
| Extensions | Read the versioned, non-secret health sidecar | Must not read the encrypted vault or secret values |

`pushkey_cloud_api.py` is the only deployable cloud service. The legacy
`server/main.py` service has been archived after parity for activation,
heartbeat, deactivation, device-limit, and signed-token behavior landed in the
canonical service. Historical context is recorded in
`docs/legacy-server-archive.md`; no new route or behavior may be added under
`server/`.

## License authority and device lifecycle

The license record in the canonical service is authoritative for:

- tier and device limit;
- active, expired, or revoked status;
- expiry time;
- registered device fingerprints; and
- the tier embedded in a signed device token.

The client may send legacy `tier`, `email`, or `max_devices` fields during
activation, but the service ignores them when deciding entitlement. Device
state is currently stored under the license record in `licenses.json`; Phase 4
will migrate this state to transactional storage without changing the v1
contract.

The supported lifecycle is:

1. `POST /v1/activate` validates the authoritative record, enforces the device
   limit, registers or refreshes a fingerprint, and returns a signed token.
2. `POST /v1/heartbeat` verifies that registration and token, refreshes device
   telemetry, and rotates the signed token.
3. `POST /v1/deactivate` verifies the current signed device token and removes
   that fingerprint. A later heartbeat is rejected until activation.

Revoked and expired licenses cannot activate or heartbeat. Re-activating the
same fingerprint is idempotent and does not consume another device slot.

## API compatibility

`/v1/*` is the canonical device-license namespace. `/api/v1/activate`,
`/api/v1/heartbeat`, and `/api/v1/deactivate` are compatibility aliases with
identical behavior.

Both `/v1/heartbeat` and its `/api/v1/heartbeat` compatibility alias require a
fingerprint and signed token. Aggregate telemetry is available only through
authenticated administration endpoints; there is no public telemetry bypass.

The JSON compatibility store uses a module lock and atomic `os.replace` for
single-process read/modify/write safety. It is not a distributed lock:
multi-worker safety remains explicitly deferred to the Phase 4 database
migration. Deployments must run exactly one worker and one machine until that
migration lands. Activate, heartbeat, and deactivate also use an in-process limiter;
the distributed limiter remains Phase 5 work.

The checked contract is [cloud-license-v1.openapi.json](cloud-license-v1.openapi.json).
FastAPI's generated OpenAPI remains available to tests through `app.openapi()`;
production documentation exposure is intentionally disabled.

## Other version boundaries

- Vault V3 is current. V1 and V2 are read/migrate compatibility formats and are
  never written by new production paths.
- The local API contract is represented by `web-app/src/lib/api.ts` and
  `pushkey_local_api.py`. Formal endpoint-by-endpoint checking remains a
  separate Phase 1 slice.
- The extension health sidecar is non-secret local metadata. Its formal schema
  versioning remains a separate Phase 1 slice.
# Proxy trust and client IPs

Production commands currently pass `--no-proxy-headers`. Rate limiting therefore
uses the immediate TCP peer address and never trusts arbitrary client-supplied
`X-Forwarded-For` values. A deployment may enable proxy headers only after setting
Uvicorn's `--forwarded-allow-ips` to the exact addresses or networks of its trusted
load balancers. Do not use `*` on an internet-reachable service.

Lifecycle rate limiting uses license identity plus a process-global bucket. This
prevents every customer behind one ingress peer from sharing a single IP quota.
Per-IP lifecycle limiting is deferred until the trusted-proxy integration phase;
it must not be advertised or enabled while deployments use
`--no-proxy-headers`.

## Client compatibility and forced upgrades

- Vault files: V3 is current; V1 and V2 are read/migrate compatibility formats
  and are never written by new production paths.
- Cloud device API: `/v1/activate`, `/v1/heartbeat`, and `/v1/deactivate` are
  stable for the initial production line. `/api/v1/*` remains a compatibility
  alias with identical behavior.
- Local API: v1 is the contract documented in `docs/local-api-v1.md`; breaking
  route removals or response-shape removals require a new local API version.
- Health sidecar: v1 is the contract documented in
  `docs/health-sidecar-v1.md`; consumers must tolerate unknown fields.
- Forced upgrade rule: clients may be forced to upgrade only for security
  defects, unsupported vault/API versions, revoked licensing behavior, or cloud
  protocol incompatibility. Non-security UI changes must preserve compatibility
  for the current production line.
- Server response rule: cloud endpoints should return explicit unsupported
  version errors rather than silently downgrading entitlement or sync behavior.
