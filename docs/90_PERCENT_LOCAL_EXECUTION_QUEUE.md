# Pushkey 90 Percent Local Execution Queue

Status date: 2026-07-24

This queue is the small local slice that can still move the roadmap toward the
90 percent mark without relying on signing credentials, production
infrastructure, branch protection settings, or external review artifacts.

## Immediate Goals

- [x] Prove the local web app critical journeys still pass in Chromium,
  Firefox, and WebKit using the existing Playwright matrix.
- [x] Add an automated accessibility smoke for the locked and unlocked local
  shell so the critical journey audit has explicit evidence.
- [x] Re-run the roadmap tracker and only update the production checklist if the
  measured count moves.

## Outcome

- Measured production progress is now 317/337, or 94.1%.
- The new accessibility smoke lives in
  [web-app/tests/e2e/accessibility.spec.ts](../web-app/tests/e2e/accessibility.spec.ts).
- The local Track A load-test evidence lives in
  [docs/alpha-capacity-load-results.json](./alpha-capacity-load-results.json).
- The tracker is already above the 90 percent mark, and the remaining blockers
  are external Track D work.

## Not In Scope

- [ ] Signing artifacts.
- [ ] Production backup or rollback drills.
- [x] Branch protection / release-gate enforcement in GitHub.
- [ ] Independent security review or penetration testing.
- [ ] Production monitoring evidence, backup or rollback drills.

See
[production-external-gate-handoff-checklist.md](./production-external-gate-handoff-checklist.md)
for the evidence fields and operator handoff record.

## Working Rule

Do not mark a roadmap item complete until the code, tests, or evidence record
exists in the repo and has been verified locally.
