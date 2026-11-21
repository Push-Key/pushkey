# Pushkey Support And Security Policy

Status: Phase 11 policy draft for launch readiness.

## Supported Platforms

Verified baseline:

- Windows 11
- Python 3.12
- Node 24
- npm 11

Initial launch claim:

- Windows is the first supported desktop/build platform.
- macOS and Linux are supported only after CI, packaging, and install tests cover
  the claimed OS/architecture pair.
- Browser and VS Code extensions are beta/deferred unless Phase 9 store/package
  gates pass.

## Lifecycle Policy

- Current production line: local API v1, health sidecar v1, cloud device API v1,
  vault V3.
- V1/V2 vault files are migration-only compatibility formats.
- Security fixes may force client upgrades.
- Non-security UI changes must preserve compatibility within the current
  production line.

## Vulnerability Reporting

Security issues should be reported privately before public disclosure.

Required report contents:

- affected version or commit;
- affected component;
- reproduction steps;
- impact assessment;
- whether secrets, tokens, or account data may be exposed.

Response targets:

- critical: acknowledge within 24 hours;
- high: acknowledge within 2 business days;
- medium/low: acknowledge within 5 business days.

## Support Severity Levels

- Severity 1: suspected secret exposure, vault corruption, account takeover, or
  production cloud outage.
- Severity 2: paid user blocked from activation, sync, recovery, or billing.
- Severity 3: degraded feature, extension problem, admin issue, or docs gap.
- Severity 4: general question, enhancement request, or non-blocking bug.

## Incident Communication Template

Required sections:

- incident ID;
- start time and detection time;
- affected systems;
- customer impact;
- current status;
- mitigation;
- next update time;
- final root cause after resolution.
