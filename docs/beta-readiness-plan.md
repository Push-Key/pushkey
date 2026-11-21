# Pushkey Beta Readiness Plan

## 1. Where We Stand

- **Alpha is shipped.** The local-first desktop app is out as **v0.1.1-alpha**. It works without any cloud dependency.
- **The cloud backend is built but deployed nowhere.** `pushkey_cloud_api.py` (FastAPI) is complete, the Dockerfile/`fly.toml`/`railway.toml` are largely correct, but neither `pushkey-api.fly.dev` nor `api.pushkey.dev` resolves. Nothing is reachable.
- **The public-beta / GA gate is 0/22 complete.** Every gate item requires the cloud backend deployed, code signing enabled, managed backups proven, and an independent security review — **none of which can be closed from the repo alone.** Every remaining item needs money, hosted infrastructure, or a third party.
- **The scaffolding is done.** Deploy configs, the entire CI signing pipeline, the backup runbooks and drill scripts, the alert-rule spec, and the security-review evidence pack all exist in-repo and are dormant, waiting on external inputs.

The honest summary: this is **not an engineering-effort problem, it is a procurement-and-deployment problem.** The long poles are billing approval, domain/DNS control, certificate issuance, and third-party engagements — not code.

---

## 2. Critical Path — What Unblocks What

There is one load-bearing action that everything downstream depends on:

```
        ┌─────────────────────────────────────────────────────────┐
        │  DEPLOY THE CLOUD API  (Fly.io, ~1–2 hrs)                │
        │  the single gate that unblocks four separate workstreams │
        └───────────────┬─────────────────────────────────────────┘
                        │
   ┌────────────────────┼────────────────────┬───────────────────────┐
   ▼                    ▼                    ▼                       ▼
 Uptime check      Live monitoring       Pen-test of the        Backup / restore
 (free pinger)     (deploy 7 alert       LIVE cloud API,        + rollback drills
                   rules to backend)     admin, portal, sync    (need hosted DB+store)
                        │
                        └── both already have proven alert *delivery* (2026-07-22);
                            they only lack a live target to fire against.
```

Independent of the cloud deploy, two workstreams can start **in parallel today**:

- **Code signing** — gated on certificates/keys, not on the API. The Ed25519 signature path is $0 and self-service and can be turned on immediately.
- **Security-review baseline freeze + evidence pack** — repo-local prep with no blocker; the *engagement itself* needs the API deployed so the pen-tester has a live target.

Ordering rules that matter:

1. **Reconcile the canonical domain before wiring any DNS.** The repo mixes three brands (`api.pushkey.dev` client default, `pushkey.app` APP_URL, `push-key.com` CORS allowlist). Pick one first or activation/email-links/CORS break for whichever is wrong.
2. **Set `PUSHKEY_TRUSTED_HOSTS` at deploy time** — undocumented but mandatory. Without it `TrustedHostMiddleware` 400-rejects every external request; the health endpoint is unreachable even after a "successful" deploy.
3. **Wire object storage to Supabase before running any restore drill.** Today `_VaultStore` writes ciphertext blobs to local disk, not the bucket. Until that code path exists, DB backups restore metadata pointing at blobs that were never durably stored — the drills cannot honestly prove combined metadata+blob restore.
4. **Deploy the API before commissioning the pen test.** The pen-test scope explicitly covers the live cloud API/admin/portal/sync; there is nothing to test until it is up.

---

## 3. Work Grouped by What It Needs

None of these close from the repo alone. Grouped by the type of external unblock.

### A. Self-service / $0 (do these now, no dependency)
- **Ed25519 release-signing key** → set `PUSHKEY_RELEASE_PRIVATE_KEY_PEM`. Minutes, $0. **Caveat:** the public half is already pinned in `npm/release-public-key.pem` and shipped in the npm package — you must load the *mate* of that key, not a fresh one, or every `.sig` verification fails. If the original private key is lost, regenerate the pair AND re-publish npm with the new public key.
- **Security-review baseline freeze + evidence pack** — bundle SECURITY.md, ARCHITECTURE.md, the 2 ADRs, the OpenAPI/local-api/health-sidecar/admin-auth docs, and Phase-8 supply-chain evidence. 2–4 days engineering.
- **Documentation fix:** add `PUSHKEY_TRUSTED_HOSTS` to `.env.example` and `DEPLOY.md`. Minutes.

### B. Needs Hosted Infrastructure
- **Deploy the cloud API** (Fly.io — a single machine + 1GB volume + SQLite is sufficient for beta; Postgres/Redis are optional). ~1–2 hrs.
- **Production + staging deployments pointed at hosted Postgres and the object bucket** (needed so drill `--target-*` flags have a reachable target). ~2–3 days.
- **Hosted monitoring backend** (Grafana/Prometheus, Datadog, or equivalent) to receive the 7-rule spec. ~2–5 days including the uptime check.
- **External uptime pinger** against `/api/v1/health` — free tier is sufficient.
- **GitHub Actions secret store / `release` environment** — already configured; just load secrets.

### C. Needs Money (paid subscriptions/certs)
- **Supabase Pro** (~$25/mo/org) → managed daily backups, 7-day retention. Baseline out of the current *zero-managed-backup* Free-tier state.
- **Supabase PITR add-on** (~$100/mo+ smallest tier; 7/14/28-day window) → minutes-level RPO. Required for "point-in-time recovery proven by a destructive restore drill."
- **Apple Developer Program** ($99/yr) → Developer ID Application cert + notarization API key.
- **Windows code-signing cert** (~$80–130/yr Certum individual up to ~$400–600/yr DigiCert/Sectigo EV). See the hardware caveat below.
- **Independent security review** — five-figure engagement.
- **Penetration test** — five-figure engagement.
- *(Recurring signing cost alone: ~$180–700/yr. Recurring Supabase for full backup posture: ~$125+/mo.)*

### D. Needs a Third Party (an external actor must act)
- **Control of `pushkey.dev` DNS** at the registrar → create `api.pushkey.dev`, let Fly issue the LetsEncrypt cert.
- **SMTP provider credentials** (Gmail app password / SendGrid / SES) for license, invite, and reset emails. Email degrades gracefully if absent, but license delivery will not work.
- **CA identity validation** for the Windows cert (days to weeks) and Apple org enrollment with D-U-N-S (days).
- **Supabase management token** with scope to read live backup/PITR schedule for ref `viehwjyjwuefsqthindb` (current token cannot).
- **Private-repo access** (`server/`, `web/`) granted to the pen-test firm.
- **Security reviewer + pen-test firm** contracted and scheduled (3–6 weeks vendor calendar).
- **On-call operator** during the restore/rollback drill windows.

---

## 4. Item-by-Item: Steps, Effort, Cost, Calendar

### 4.1 Deploy the Cloud API (Fly.io)
**Steps:** `fly auth login` → `fly launch --copy-config --no-deploy` (or `fly apps create pushkey-api`) → `fly volumes create pushkey_data --size 1 --region iad` → set required secrets `PUSHKEY_JWT_SECRET`, `PUSHKEY_ADMIN_EMAIL`, `PUSHKEY_ADMIN_PASSWORD` (all three are fatal-on-missing in production) → **set `PUSHKEY_TRUSTED_HOSTS='pushkey-api.fly.dev,api.pushkey.dev'`** (mandatory) → set `ADMIN_ORIGIN` and SMTP vars → `fly deploy` → `curl https://pushkey-api.fly.dev/api/v1/health` expect `200 {"status":"ok","service":"pushkey-cloud"}` → `fly certs add api.pushkey.dev` + DNS CNAME → point client (DNS default resolves, or bake `PUSHKEY_SERVER` into the exe) and set Vercel `NEXT_PUBLIC_ADMIN_API_URL`.
**Effort:** ~1–2 hrs hands-on. **Cost:** Fly billing (a few $/mo at this size). **Calendar:** same-day, +15–60 min DNS/cert propagation. Fly is the fastest path because Dockerfile+fly.toml+volume are already tailored to it; Railway's config has no volume so SQLite wouldn't persist.

### 4.2 Backups + Object Storage on Supabase
**Steps:** Upgrade Free→Pro → enable PITR add-on + pick retention → verify live schedule via management plane → **wire `_VaultStore._write_object/_read_object/_delete_object` to Supabase Storage** (the real code gap; blobs currently land on local disk) → choose a versioning strategy (recommend app-level append-only object keys, since Supabase Storage has no native S3 versioning; S3/R2 versioned sync is the GA upgrade) → deploy prod+staging against hosted Postgres and the bucket → run `scripts/production_restore_drill.py` (destructive) → run `scripts/production_rollback_drill.py` → capture the full evidence set.
**Effort:** ~2–3 engineering weeks. The load-bearing item is the Supabase Storage backend: ~3–5 days (append-only), +2–4 days if adding S3/R2 versioned sync; prod+staging deploy ~2–3 days; both drills + evidence ~2–3 days. **Cost:** ~$25/mo Pro + ~$100/mo+ PITR + variable egress. **Calendar:** ~2–4 weeks, gated mainly on billing approval and management-token access.

### 4.3 Code Signing (three surfaces, all dormant in `release.yml`, zero code change)
**Steps:**
- **Ed25519** (free, now): load `PUSHKEY_RELEASE_PRIVATE_KEY_PEM` (the mate of the committed public key). Minutes.
- **Windows Authenticode:** obtain OV/EV cert → produce `.pfx` → base64 → set `PUSHKEY_WINDOWS_CERT_BASE64` + `_PASSWORD`. **Hardware caveat:** since June 2023, publicly-trusted OV/EV keys must live on FIPS hardware/HSM, which conflicts with the workflow's exportable-`.pfx` model. The realistic exportable path is Certum's cloud Simply-Sign card (~$80–130/yr); a cloud-HSM model would need a workflow change (out of no-code-change scope).
- **Apple codesign+notarize:** enroll in Apple Developer Program → create Developer ID Application cert → export `.p12` → set `PUSHKEY_APPLE_CERT_BASE64` + `_PASSWORD` + `_SIGNING_IDENTITY` (set explicitly via `security find-identity`) → create App Store Connect API key → set the `_NOTARIZATION_API_KEY` / `_KEY_ID` / `_ISSUER` trio (notarization is independently optional but strongly recommended or Gatekeeper still warns).
- Load all 9 secrets, push a `v*` tag. Recommended dry run: Ed25519 first, then Windows, then Apple.
**Effort:** ~1–2 hrs to wire secrets once certs are in hand. **Cost:** ~$180–700/yr recurring. **Calendar:** 1–3 weeks, dominated entirely by CA/Apple identity validation (Ed25519 = minutes; Apple org enrollment with D-U-N-S and Windows OV/EV validation are the slow poles).

### 4.4 Security Review + Monitoring Activation
**Steps:** freeze baseline + assemble evidence pack (repo-local) → commission independent crypto/app-sec review (validate V3 vault: Argon2id t=3/m=64MB/p=4, AES-256-GCM slots, 80-bit recovery codes, the documented KDF-identifier gap, zero-knowledge sync, loopback web-app boundary) → commission pen test across cloud API/admin/portal/local API/MCP/extensions/sync (**requires deployed API + private-repo access**) → triage/resolve via `docs/security-review-findings-tracker.md` (every Critical/High must reach Resolved or the release does not ship; Medium/Low need owner+deadline) → cross-functional sign-off (Eng/Security/Ops/Product/Legal) → apply the 7 alert rules to a live backend → add the external uptime check → run the deferred backup/rollback drills.
**Effort:** repo-local prep 2–4 days; findings resolution 1–3 weeks depending on Critical/High count; monitoring activation ~2–5 days but fully gated on the deployed API. **Cost:** two five-figure engagements + paid hosting tiers. **Calendar:** external review + pen test run 3–6 weeks of vendor calendar once scoped/contracted; **end-to-end 6–10 weeks**, dominated by third-party lead time and the live-environment dependency.

---

## 5. Two Bars: Private Beta vs Full GA

### CHEAPEST PATH TO A PRIVATE BETA
*Goal: a reachable, backed-up, signed build in the hands of invited testers — without waiting on five-figure engagements.*

1. **Deploy the cloud API to Fly.** ~1–2 hrs. (Item 4.1)
2. **Upgrade Supabase to Pro** for managed daily backups + wire the Supabase Storage object path so blobs are durable. Skip PITR for now (accept up-to-24h RPO as the beta bar). ~1 week + ~$25/mo. (Item 4.2, reduced scope)
3. **Turn on signing:** Ed25519 immediately ($0); add Apple ($99/yr) and a Certum Windows cert (~$80–130/yr) as they arrive. (Item 4.3)
4. **Wire the free uptime pinger + deploy the alert rules** to a free/low-cost monitoring backend — delivery is already proven, it just needs a live target. (Item 4.4, monitoring only)

**Realistic cost:** ~$25/mo Supabase + ~$180–230/yr signing + minimal Fly hosting.
**Realistic calendar:** **~1–3 weeks**, gated on the canonical-domain decision, DNS control, SMTP account, and cert validation lead time. Same-day for the deploy itself if those are ready.

### FULL GA BAR (everything the 22-item gate demands)
Everything above, **plus**:

1. **Supabase PITR add-on** (~$100/mo+) for minutes-level RPO, and a chosen object-versioning strategy proven by drill.
2. **Independent crypto/app-sec review** — five figures, 3–6 weeks vendor time.
3. **Penetration test** across all named surfaces against the live API with private-repo access — five figures.
4. **All Critical/High findings resolved to zero; every Medium/Low triaged; cross-functional sign-off filled with real Go/No-Go decisions.**
5. **Destructive restore drill + deployment rollback drill run against hosted staging/prod**, with the full evidence set captured (RPO/RTO measured, metadata↔blob reconciliation, post-restore smoke tests).
6. **Notarization + EV/reputation** so Gatekeeper and SmartScreen are clean for public distribution.

**Realistic cost:** two five-figure engagements + ~$125+/mo hosting/backup + ~$180–700/yr signing.
**Realistic calendar:** **6–10 weeks**, dominated by third-party engagement lead time and the dependency on a live hosted environment. Do not commission the audit until alpha feedback has stopped reshaping the product — the plan explicitly warns against auditing code that will still change.

---

## 6. Open Questions the Operator Must Answer to Start

These block the first moves. Nothing meaningful starts until the first three are decided.

1. **Which domain is canonical** — `api.pushkey.dev` (client default), `pushkey.app` (APP_URL), or `push-key.com` (CORS allowlist)? They disagree today, and DNS/CORS/email-links break for whichever stays inconsistent. **Decide before wiring any DNS.**
2. **Is `pushkey.dev` registered and its DNS zone controllable**, so `api.pushkey.dev` can point at Fly with a Fly-issued cert? If not, bake `PUSHKEY_SERVER=https://pushkey-api.fly.dev` into the desktop build instead.
3. **Which SMTP provider/account** is used for beta license and invite emails?
4. **Is billing approved for Supabase Pro only (daily, ~24h RPO) or Pro + PITR (minutes RPO)?** This sets the beta backup bar and gates the whole backup workstream.
5. **Is the Supabase Storage object-path wiring in scope for beta?** Without it, the restore drills cannot honestly prove combined metadata+blob restore. And which versioning strategy — app-level append-only keys, or a true versioned S3/R2 backup-of-record?
6. **Does the original Ed25519 private key (mate of the committed `npm/release-public-key.pem`) still exist?** If lost, npm must be re-published with a new public key or all `.sig` verifications fail.
7. **For Windows signing: is an exportable soft `.pfx` obtainable (e.g. Certum cloud card), or must you move to a cloud-HSM model** that would require a workflow change beyond the no-code-change goal?
8. **Is Apple enrollment individual or organizational?** Org enrollment needs a D-U-N-S number and takes longer but puts a company name in the signature.
9. **Which monitoring backend** (Grafana/Prometheus, Datadog, or equivalent) do we standardize on, so the provider-agnostic 7-rule spec can be translated?
10. **Has alpha stabilized enough to freeze a security-review baseline,** and is a management token with backup/PITR read scope obtainable for the Supabase project?
11. **Should `npm/scripts/install.js` be tightened so a missing `.sig` is a hard failure** rather than today's advisory warn-and-continue? Deliberate policy decision + a code change beyond turning CI secrets on.