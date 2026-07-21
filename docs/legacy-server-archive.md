# Legacy Activation Server Archive

Status: archived during Phase 1 contract lock.

The former `server/` FastAPI service was a standalone activation backend. Its
useful behavior has been migrated into the canonical cloud service,
`pushkey_cloud_api.py`:

- device activation;
- heartbeat;
- deactivation;
- device-limit enforcement;
- signed device-token behavior; and
- `/api/v1/*` compatibility aliases for the canonical `/v1/*` device API.

`pushkey_cloud_api.py` is now the only production cloud service. No deployment
entrypoint should target `server/main.py`, `server.main`, or `main:app`.

Historical context is preserved in:

- `docs/ARCHITECTURE.md`
- `docs/adr/0001-canonical-cloud-service.md`
- `docs/adr/0002-server-authoritative-entitlements.md`
- `docs/cloud-license-v1.openapi.json`
- `tests/test_license_activation_contract.py`
