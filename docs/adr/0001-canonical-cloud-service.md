# ADR 0001: Canonical cloud service

- Status: Accepted
- Date: 2026-07-19

## Decision

`pushkey_cloud_api.py` is the canonical and only production cloud service.
`server/main.py` is legacy migration reference code. Required device lifecycle
behavior is implemented and tested in the canonical service before the legacy
service is archived or removed.

## Context

Two FastAPI applications independently owned overlapping activation behavior.
The smaller service enforced device counts but trusted a client-supplied tier
and did not look up the commercial license record. The larger service owned
license issuance and status but previously implemented only aggregate
heartbeat telemetry.

## Consequences

All clients have one license authority and one deployment target. Device
registrations temporarily share the license JSON store; the planned database
migration must preserve the v1 API. No new route or behavior may be added to
`server/`.
