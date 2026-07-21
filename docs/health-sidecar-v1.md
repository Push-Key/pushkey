# Pushkey Health Sidecar v1

Status: Phase 1 contract for editor and browser extensions.

`health.json` is a non-secret local sidecar written beside the encrypted vault.
It exists so secondary clients can show rotation health without opening
`vault.enc`, asking for the master password, or reading plaintext secrets.

## Location

The canonical path is `pushkey_shared.HEALTH_FILE`, currently:

```text
~/.pushkey/health.json
```

Agents and extensions must resolve this through Pushkey configuration or the
documented default path. New production code should not hardcode parallel vault
paths.

## Shape

The file is a JSON object keyed by API key name:

```json
{
  "OPENAI_API_KEY": {
    "status": "healthy",
    "days_old": 12,
    "provider": "OpenAI",
    "category": "AI",
    "first_used": "2026-07-01T12:00:00Z",
    "last_used": "2026-07-20T12:00:00Z",
    "created": "2026-07-01T12:00:00Z",
    "rotated": "2026-07-10T12:00:00Z",
    "rotation_count": 1
  }
}
```

Required keys for each entry:

- `status`: one of `healthy`, `warning`, or `critical`.
- `days_old`: number of days since the effective rotation date, or `null` if
  unknown.
- `provider`: provider name or `null`.
- `category`: display category.
- `first_used`: timestamp string or `null`.
- `last_used`: timestamp string or `null`.
- `created`: timestamp string or `null`.
- `rotated`: timestamp string or `null`.
- `rotation_count`: integer count.

## Security Rules

- The sidecar must never contain secret values, backup secret values, recovery codes, master-password material, salts, vault ciphertext, or license secrets.
- Consumers must treat missing, malformed, partial, or concurrently replaced
  files as an empty health object.
- Consumers must render values as text, not HTML.
- The sidecar is local metadata, not a cloud sync format.
