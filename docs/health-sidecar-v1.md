# Pushkey Health Sidecar v1

Status: Phase 1 contract for the desktop app, CLI, MCP, local API, and the
editor and browser extensions.

`health.json` is a local sidecar written beside the encrypted vault. It exists
so secondary clients can show rotation health without opening `vault.enc`,
asking for the master password, or reading plaintext secrets. It is
classified as local-sensitive metadata: key names and provider names can
reveal operational details, so it stays on the machine.

The full design, including atomic publication, locking, and error semantics,
is in
[`superpowers/specs/2026-07-20-health-sidecar-v1-design.md`](superpowers/specs/2026-07-20-health-sidecar-v1-design.md).
`pushkey_health.py` is the only module that writes, validates, or removes the
sidecar.

## Location

The canonical path is `pushkey_shared.HEALTH_FILE`, currently:

```text
~/.pushkey/health.json
```

Agents and extensions must resolve this through Pushkey configuration or the
documented default path. New production code should not hardcode parallel vault
paths.

## Shape

The file is a versioned UTF-8 JSON envelope:

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-20T12:34:56Z",
  "keys": {
    "OPENAI_API_KEY": {
      "status": "healthy",
      "days_old": 12,
      "provider": "OpenAI"
    }
  }
}
```

Root fields, all required, no others allowed:

- `schema_version`: exactly the integer `1`.
- `generated_at`: UTC timestamp, whole seconds, `Z` suffix.
- `keys`: object with 0 to 10,000 records.

Each property name in `keys` matches `^[A-Za-z_][A-Za-z0-9_]{0,127}$`. Each
record has exactly these fields:

- `status`: one of `healthy`, `warning`, `critical`, or `unknown`.
- `days_old`: integer `0..365000`, or `null` if unknown.
- `provider`: 1 to 64 printable ASCII characters, or `null`.

Unknown root or record fields, duplicate JSON keys, and documents larger than
1,048,576 bytes are rejected.

## Freshness

A snapshot is current when `generated_at` is at most 26 hours old and at most
five minutes in the future by the reader's clock. Stale or future snapshots
are unavailable. While the desktop vault is unlocked it republishes at least
every six hours. Every encrypted vault write removes the sidecar, and callers
that still hold the plaintext vault republish it.

## Legacy compatibility

Bundled readers also accept the earlier unversioned map (one object keyed by
key name) for a compatibility window. The file modification time stands in
for `generated_at`. A missing or invalid `status` becomes `unknown`. Invalid
`days_old` and `provider` values become `null`. Extra fields such as
`category`, timestamps, and rotation counts are ignored. A document that mixes
legacy entries with envelope fields is rejected. Legacy support is removed
once the shipped extensions that understand v1 have passed packaging and
install verification.

## Security Rules

- The sidecar must never contain secret values, backup secret values,
  recovery codes, master-password material, salts, vault ciphertext, token
  material, notes, project or path data, created/rotated/used timestamps,
  rotation counts, or license secrets.
- Consumers treat missing, malformed, oversized, stale, unsupported, or mixed
  documents as unavailable and clear any previously shown health.
- Consumers must render values as text, not HTML.
- The loopback `GET /health` endpoint on `127.0.0.1:7654` returns the validated
  envelope with HTTP 200, or a small fixed error with HTTP 503. It never
  returns raw file bytes.
- The sidecar is local metadata, not a cloud sync format.
