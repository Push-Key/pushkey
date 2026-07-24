# Pushkey Alpha Launch Task List

Status date: 2026-07-24

> **DONE — the local-first alpha shipped on 2026-07-24.** PR #3 merged to
> `main`, all required CI checks passed on the release commit `aebb37c`, and
> `v0.1.1-alpha` was published (provenance-verified; Windows/macOS/Linux
> binaries with SHA-256 checksums, SBOM, and provenance evidence).
> `v0.1.0-alpha` is marked superseded. The two cloud-ops tasks below (managed
> database backups, uptime check) moved to the deferred bucket because the
> production cloud API is not deployed for this local-first alpha — there is no
> live service to back up or monitor yet. The historical task write-ups are
> retained below for when the cloud backend goes live.

Current state:

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

```
Alpha launch:                       323/323 = 100.0%
Public beta / GA gates (deferred):    0/22  =   0.0%
Post-launch agentic review:           0/3   =   0.0%
```

Everything in the deferred buckets is scheduled after alpha on purpose. See
"How This Plan Is Scored" in `PRODUCTION_READINESS_PLAN.md`.

---

## Task 1 — Land the branch and get CI green

**Why:** `main` requires pull-request review, so nothing merges without you.
This is also the first time the accessibility gate, the release-provenance
gate, and the dependency fixes run in real CI rather than on one machine.

**Do:**

```bash
git push -u origin feat/pushkey-app
gh pr create --base main --title "Alpha readiness: accessibility, release provenance, vault write fix" --body-file docs/ALPHA_LAUNCH_TASKLIST.md
gh pr checks --watch
```

**Required checks that must go green:**

| Check | Watch for |
|---|---|
| `CI / Python tests` | Windows runner, ~555 tests |
| `CI / Web build` | |
| `CI / Local web app build` | **New step.** Installs a Chromium browser and runs the axe-core WCAG scans. Has never run in CI before — most likely place for a surprise. |
| `CI / Package smoke (windows-latest)` | |
| `CI / Package smoke (ubuntu-latest)` | |
| `CI / Package smoke (macos-latest)` | |
| `CI / Security scans` | Gitleaks, pip-audit, `npm audit --audit-level=high`, Bandit/Semgrep, Trivy |

**If the accessibility step fails:** the run uploads a
`web-app-accessibility-traces` artifact. Download it and open the trace:

```bash
gh run download <run-id> -n web-app-accessibility-traces
npx playwright show-trace test-results/<failing-test>/trace.zip
```

Contrast values are computed from CSS, not fonts, so they should not differ
between your machine and a Linux runner. The realistic failure mode is the dev
server exceeding the 120s startup budget on a cold runner, which is a retry,
not a code problem.

**Then merge the PR.** Squash or merge commit, your preference.

- [x] Branch pushed, PR opened (PR #3, 2026-07-24)
- [ ] All seven required checks green
- [ ] PR merged to `main`

---

## Task 2 — Turn on managed database backups

**Why:** if the hosted database is lost today, there is no recovery path. This
is the cheap version of the deferred "encrypted backups with point-in-time
recovery" item: a provider toggle, not a backup architecture.

**Scope note:** vaults are local-first and cloud sync is opt-in encrypted
blobs, so a cloud incident is not the same as users losing their keys. That is
why the toggle is enough for alpha and the full PITR design can wait.

**Do:** open your hosting provider's console, enable automated backups on the
production database, and set the longest retention the current plan allows.

**Record the evidence** in
`production-rollback-backup-infrastructure-checklist.md`:

- provider and database identifier
- backup schedule
- retention window
- timestamp of the first successful automated backup

- [ ] Automated backups enabled
- [ ] First backup confirmed present
- [ ] Evidence recorded

---

## Task 3 — Add an external uptime check

**Why:** alert delivery to the accountable operator is already proven working
end to end (SMTP acceptance plus IMAP receipt). What is missing is the thing
that *notices* an outage and fires it. Right now nothing does.

**Do:** point any free-tier uptime service at the cloud API health endpoint.
Check every 5 minutes, alert to the accountable-operator mailbox already
recorded in `ops-readiness.md`. Any of the usual free tiers is fine.

Alert thresholds and the signals worth watching are already specified in
`production-monitoring-alert-rules.yaml` — that file is provider-agnostic and
ready to apply when you pick a monitoring backend. For alpha you only need the
health check.

**Record** the service, endpoint, interval, and destination in
`ops-readiness.md`.

- [ ] Uptime check live
- [ ] Test alert received at the operator mailbox
- [ ] Evidence recorded

---

## Task 4 — Cut a new alpha tag

**Depends on Task 1 being merged.** The release workflow's `verify-provenance`
job refuses to build unless the tagged commit is contained in `main` and every
required check passed on it. Tagging before the merge will fail by design.

**Why this is not optional:** the published `v0.1.0-alpha` binaries predate the
vault write-loss fix. On those builds, two rapid key edits silently discard the
second — no error, no warning. A tester who hits it concludes the product is
flaky and stops using it without telling you why. You would lose the tester and
learn nothing.

**Do:**

```bash
git checkout main && git pull
git tag v0.1.1-alpha
git push origin v0.1.1-alpha
gh run watch
```

The release workflow will verify provenance, build binaries for Windows, macOS,
and Linux, generate SBOM and SHA-256 checksums, attest provenance, and publish.
Signing steps skip themselves cleanly while no certificates are configured.

**Then:**

- [ ] `verify-provenance` passed
- [ ] Release published with binaries and `SHA256SUMS.txt`
- [ ] Release notes state: alpha, unsigned, verify the checksum
- [ ] Old `v0.1.0-alpha` release marked superseded so nobody downloads it
- [ ] `release-readiness.md` updated with the new tag and commit SHA

---

## Done means

```powershell
.\.venv\Scripts\python.exe scripts\roadmap_progress.py
```

reports `Alpha launch: 323/323 = 100.0%`, and there is a published build that
testers can safely install. Both are now true: `v0.1.1-alpha` is published.

## Explicitly not in scope

Deferred until after alpha feedback, so that certificates and audits are not
paid for twice on code that is about to change:

- code signing for Windows and macOS
- encrypted backups with point-in-time recovery, versioned object storage
- destructive restore and production rollback drills
- independent security review and penetration testing

Applying the drafted release tag ruleset
(`scripts/apply_release_tag_ruleset.py --apply`) and commissioning the manual
accessibility review are both available whenever you want them. Neither blocks
alpha.
