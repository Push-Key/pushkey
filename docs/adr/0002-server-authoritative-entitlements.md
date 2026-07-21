# ADR 0002: Server-authoritative entitlements

- Status: Accepted
- Date: 2026-07-19

## Decision

Tier, status, expiry, and device limits are derived exclusively from the
canonical server's license record. Client-supplied entitlement fields are
ignored. Device tokens are HMAC-signed, expire after seven days by default,
and are bound to a version, audience, license hash, fingerprint, and
authoritative tier using a domain-separated signing key.

The stable device API is `/v1/activate`, `/v1/heartbeat`, and
`/v1/deactivate`. `/api/v1/*` is retained as a compatibility alias.

## Consequences

Changing a request's `tier` or `max_devices` cannot upgrade a license.
Deactivation invalidates subsequent heartbeats because the registration is
checked even if a previously issued token is still cryptographically valid.
The signing secret must remain stable across instances and deployments.
