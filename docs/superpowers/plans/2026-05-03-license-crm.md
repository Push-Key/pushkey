# License CRM & Key Issuance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CRM-style key issuance flow to the admin dashboard — issue keys to contacts by email, track sales stage and follow-ups, view a contacts page grouping licenses by person.

**Architecture:** Extend the flat `licenses.json` record with 6 CRM fields. Add 4 new FastAPI endpoints (issue, contacts, update_contact, send_invite) to `pushkey_cloud_api.py`. Add `IssueKeyPanel` to the licenses page, a new `/admin/contacts` page, and a Contacts nav item. Email sending uses `smtplib` (stdlib) configured via env vars.

**Tech Stack:** Python/FastAPI (backend), Next.js/TypeScript (frontend), smtplib (email), lucide-react (icons).

---

## File Map

| File | Change |
|------|--------|
| `pushkey_cloud_api.py` | Add `_send_invite_email()`, `issue` endpoint, `contacts` endpoint, `update_contact` endpoint, `send_invite` endpoint, lazy auto-expiry in list endpoints |
| `web/src/lib/admin-api.ts` | Extend `License` type, add `Contact` type, add `issueKey`, `getContacts`, `updateContact`, `sendInvite` methods |
| `web/src/app/admin/licenses/page.tsx` | Add `IssueKeyPanel` component, "Issue Key" button, `name/company` sub-text in table rows, `expires_at` column |
| `web/src/app/admin/contacts/page.tsx` | New file — contacts view with cards |
| `web/src/app/admin/layout.tsx` | Add Contacts nav item |

---

## Task 1: Backend — extend data model + add issue endpoint

**Files:**
- Modify: `pushkey_cloud_api.py`
- Test: manual with `curl` (FastAPI has no test suite — verify with curl commands)

- [ ] **Step 1: Add `_send_invite_email` helper after `_gen_key`**

Find `_gen_key` in `pushkey_cloud_api.py` (around line 231). Add after it:

```python
SMTP_HOST  = os.environ.get("SMTP_HOST", "")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER  = os.environ.get("SMTP_USER", "")
SMTP_PASS  = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)
APP_URL    = os.environ.get("APP_URL", "https://pushkey.app")


def _send_invite_email(to_email: str, name: str, tier: str, key: str, expires_at: str | None) -> dict:
    if not SMTP_HOST:
        return {"sent": False, "reason": "smtp_not_configured"}
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    display_name = name or to_email.split("@")[0]
    tier_label   = tier.capitalize()
    expiry_line  = f"\nThis key expires on {expires_at[:10]}.\n" if expires_at else ""

    plain = f"""Hi {display_name},

Here's your Pushkey {tier_label} license key:

  {key}

To activate:
1. Download Pushkey: {APP_URL}/download
2. Open Settings → License
3. Enter your key
{expiry_line}
Questions? Reply to this email.
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Pushkey {tier_label} access key"
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to_email
    msg.attach(MIMEText(plain, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        return {"sent": True}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)}
```

- [ ] **Step 2: Add `_auto_expire` helper + call it in list endpoint**

Add this function after `_send_invite_email`:

```python
def _auto_expire(lic: dict) -> bool:
    """Set status=expired for any record past its expires_at. Returns True if any changed."""
    now = datetime.utcnow().isoformat()
    changed = False
    for entry in lic.values():
        if (
            entry.get("expires_at")
            and entry["status"] == "active"
            and entry["expires_at"] < now
        ):
            entry["status"] = "expired"
            entry["stage"]  = "churned"
            changed = True
    return changed
```

Then find `admin_list_licenses` (around line 263) and update it:

```python
@app.get("/api/admin/licenses")
async def admin_list_licenses(_: None = Depends(_require_admin)):
    lic = _load_licenses()
    if _auto_expire(lic):
        _save_licenses(lic)
    return list(lic.values())
```

- [ ] **Step 3: Add the `issue` endpoint**

Add after `admin_generate` (around line 291):

```python
VALID_SOURCES = {"Twitter", "ProductHunt", "Referral", "Direct", "Conference", "Other"}
VALID_TRIAL_DAYS = {7, 14, 30}


@app.post("/api/admin/licenses/issue")
async def admin_issue(request: Request, _: None = Depends(_require_admin)):
    body       = await request.json()
    tier       = body.get("tier", "free").lower()
    email      = body.get("email", "").strip().lower()
    name       = body.get("name", "").strip()
    company    = body.get("company", "").strip()
    source     = body.get("source", "Direct").strip()
    trial_days = body.get("trial_days")  # int or null
    follow_up  = body.get("follow_up_date", "")
    notes      = body.get("notes", "").strip()
    send_email = bool(body.get("send_email", False))

    if tier not in TIER_PREFIXES:
        raise HTTPException(400, f"tier must be one of: {list(TIER_PREFIXES)}")
    if not email:
        raise HTTPException(400, "email is required")
    if source not in VALID_SOURCES:
        source = "Other"
    if trial_days is not None and trial_days not in VALID_TRIAL_DAYS:
        raise HTTPException(400, f"trial_days must be one of: {list(VALID_TRIAL_DAYS)} or null")

    expires_at = None
    if trial_days:
        expires_at = (datetime.utcnow() + timedelta(days=trial_days)).isoformat()

    lic = _load_licenses()
    key = _gen_key(tier)
    while key in lic:
        key = _gen_key(tier)

    entry = {
        "key":            key,
        "tier":           tier,
        "email":          email,
        "name":           name,
        "company":        company,
        "source":         source,
        "platform":       "",
        "activated":      datetime.utcnow().isoformat(),
        "last_heartbeat": None,
        "status":         "active",
        "notes":          notes,
        "expires_at":     expires_at,
        "follow_up_date": follow_up,
        "stage":          "trial" if trial_days else "active",
        "sent_invite":    False,
    }

    email_result = {"sent": False, "reason": "not_requested"}
    if send_email:
        email_result = _send_invite_email(email, name, tier, key, expires_at)
        entry["sent_invite"] = email_result.get("sent", False)

    lic[key] = entry
    _save_licenses(lic)
    _log_event("issued", {"key": key[:8] + "…", "tier": tier, "email": email})
    return {**entry, "email_result": email_result}
```

- [ ] **Step 4: Add `contacts` endpoint**

Add after the `issue` endpoint:

```python
@app.get("/api/admin/contacts")
async def admin_contacts(_: None = Depends(_require_admin)):
    lic = _load_licenses()
    if _auto_expire(lic):
        _save_licenses(lic)

    by_email: dict[str, dict] = {}
    for entry in lic.values():
        email = entry.get("email", "").lower()
        if not email:
            continue
        if email not in by_email:
            by_email[email] = {
                "email":           email,
                "name":            entry.get("name", ""),
                "company":         entry.get("company", ""),
                "source":          entry.get("source", ""),
                "follow_up_date":  entry.get("follow_up_date", ""),
                "stage":           entry.get("stage", ""),
                "notes":           entry.get("notes", ""),
                "keys":            [],
                "latest_activity": "",
            }
        contact = by_email[email]
        # Keep most recent non-empty CRM fields
        for field in ("name", "company", "source", "notes"):
            if entry.get(field) and not contact[field]:
                contact[field] = entry[field]
        if entry.get("follow_up_date") and not contact["follow_up_date"]:
            contact["follow_up_date"] = entry["follow_up_date"]
        if entry.get("stage") in ("converted",) or not contact["stage"]:
            contact["stage"] = entry.get("stage", contact["stage"])

        contact["keys"].append({
            "key":        entry["key"],
            "tier":       entry["tier"],
            "status":     entry["status"],
            "expires_at": entry.get("expires_at"),
            "activated":  entry.get("activated", ""),
        })
        act = entry.get("last_heartbeat") or entry.get("activated", "")
        if act > contact["latest_activity"]:
            contact["latest_activity"] = act

    # Sort: follow-up due first, then latest_activity desc
    today = datetime.utcnow().date().isoformat()
    result = sorted(
        by_email.values(),
        key=lambda c: (
            0 if (c["follow_up_date"] and c["follow_up_date"] <= today) else 1,
            c["latest_activity"],
        ),
        reverse=False,
    )
    # Reverse the second sort key within groups
    result.sort(key=lambda c: (
        0 if (c["follow_up_date"] and c["follow_up_date"] <= today) else 1,
        -(new_key := c["latest_activity"]) if (new_key := c["latest_activity"]) else 0,
    ))
    return result
```

- [ ] **Step 5: Add `update_contact` and `send_invite` endpoints**

```python
@app.patch("/api/admin/contacts/{email}")
async def admin_update_contact(
    email: str, request: Request, _: None = Depends(_require_admin)
):
    email = email.lower()
    body  = await request.json()
    lic   = _load_licenses()
    matched = [v for v in lic.values() if v.get("email", "").lower() == email]
    if not matched:
        raise HTTPException(404, "Contact not found")
    allowed = {"name", "company", "follow_up_date", "stage", "notes", "source"}
    for entry in matched:
        for field in allowed:
            if field in body:
                entry[field] = body[field]
    _save_licenses(lic)
    return {"ok": True, "updated": len(matched)}


@app.post("/api/admin/licenses/{key}/send-invite")
async def admin_send_invite(key: str, _: None = Depends(_require_admin)):
    lic = _load_licenses()
    if key not in lic:
        raise HTTPException(404, "License not found")
    entry  = lic[key]
    result = _send_invite_email(
        entry["email"], entry.get("name", ""), entry["tier"],
        key, entry.get("expires_at")
    )
    if result.get("sent"):
        entry["sent_invite"] = True
        _save_licenses(lic)
    return result
```

- [ ] **Step 6: Start the API and verify all 4 new endpoints respond**

```bash
cd C:/Users/aware/bots/pushkey
uvicorn pushkey_cloud_api:app --host 0.0.0.0 --port 8000 --reload
```

In a separate terminal:
```bash
# Issue a key (generate-only, no email)
curl -s -X POST http://localhost:8000/api/admin/licenses/issue \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: dev-change-me" \
  -d '{"email":"test@example.com","tier":"pro","name":"Test User","trial_days":14,"send_email":false}' | python -m json.tool

# Expected: JSON with key, tier, name, expires_at, stage="trial", sent_invite=false

# List contacts
curl -s http://localhost:8000/api/admin/contacts \
  -H "X-Admin-Secret: dev-change-me" | python -m json.tool

# Expected: array with one contact entry containing the key above

# Update contact
curl -s -X PATCH http://localhost:8000/api/admin/contacts/test%40example.com \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: dev-change-me" \
  -d '{"stage":"converted","follow_up_date":"2026-06-01"}' | python -m json.tool

# Expected: {"ok": true, "updated": 1}
```

- [ ] **Step 7: Commit**

```bash
git add pushkey_cloud_api.py
git commit -m "feat: add issue, contacts, update_contact, send_invite endpoints + auto-expiry"
```

---

## Task 2: Frontend API layer — extend types and add methods

**Files:**
- Modify: `web/src/lib/admin-api.ts`

- [ ] **Step 1: Extend `License` interface and add `Contact` + `IssueKeyRequest` types**

Open `web/src/lib/admin-api.ts`. Replace the `License` interface with:

```typescript
export interface License {
  key: string
  tier: "free" | "starter" | "pro" | "team" | "enterprise"
  email: string
  platform: string
  activated: string
  last_heartbeat: string | null
  status: "active" | "expired" | "revoked"
  notes: string
  // CRM fields (may be absent on older records)
  name?: string
  company?: string
  source?: string
  follow_up_date?: string
  expires_at?: string | null
  stage?: "trial" | "active" | "converted" | "churned" | "cold"
  sent_invite?: boolean
}

export interface ContactKey {
  key: string
  tier: License["tier"]
  status: License["status"]
  expires_at: string | null
  activated: string
}

export interface Contact {
  email: string
  name: string
  company: string
  source: string
  follow_up_date: string
  stage: string
  notes: string
  keys: ContactKey[]
  latest_activity: string
}

export interface IssueKeyRequest {
  email: string
  tier: License["tier"]
  name?: string
  company?: string
  source?: string
  trial_days?: 7 | 14 | 30 | null
  follow_up_date?: string
  notes?: string
  send_email: boolean
}

export interface IssueKeyResponse extends License {
  email_result: { sent: boolean; reason?: string }
}
```

- [ ] **Step 2: Add new methods to `adminApi`**

Inside the `adminApi` object, after the `analytics` method, add:

```typescript
  issueKey: (s: string, payload: IssueKeyRequest) =>
    call<IssueKeyResponse>(s, "/api/admin/licenses/issue", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getContacts: (s: string) =>
    call<Contact[]>(s, "/api/admin/contacts"),

  updateContact: (s: string, email: string, data: Partial<Pick<Contact, "name" | "company" | "follow_up_date" | "stage" | "notes" | "source">>) =>
    call<{ ok: boolean; updated: number }>(s, `/api/admin/contacts/${encodeURIComponent(email)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  sendInvite: (s: string, key: string) =>
    call<{ sent: boolean; reason?: string }>(s, `/api/admin/licenses/${encodeURIComponent(key)}/send-invite`, {
      method: "POST",
    }),
```

- [ ] **Step 3: Add `fmtDateOrDash` helper at bottom of file**

```typescript
export function fmtDateOrDash(iso: string | null | undefined): string {
  if (!iso) return "—"
  return new Date(iso).toISOString().slice(0, 10)
}

export function isExpiringSoon(iso: string | null | undefined): boolean {
  if (!iso) return false
  const diff = new Date(iso).getTime() - Date.now()
  return diff > 0 && diff < 7 * 24 * 60 * 60 * 1000
}

export function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false
  return dateStr <= new Date().toISOString().slice(0, 10)
}
```

- [ ] **Step 4: Build check**

```bash
cd C:/Users/aware/bots/pushkey/web
npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors related to the new types.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/admin-api.ts
git commit -m "feat: extend License type with CRM fields; add Contact, IssueKeyRequest types and API methods"
```

---

## Task 3: Licenses page — add IssueKeyPanel + table updates

**Files:**
- Modify: `web/src/app/admin/licenses/page.tsx`

- [ ] **Step 1: Add `IssueKeyPanel` component**

At the top of `web/src/app/admin/licenses/page.tsx`, after the existing imports, add:

```typescript
import { adminApi, type IssueKeyRequest, fmtDateOrDash, isExpiringSoon } from "@/lib/admin-api"
```

Then add the `IssueKeyPanel` component before the main page component (search for `export default function` to find where to insert it):

```typescript
const SOURCES = ["Twitter", "ProductHunt", "Referral", "Direct", "Conference", "Other"]
const TRIAL_OPTIONS = [
  { label: "No expiry", value: null },
  { label: "7 days",    value: 7 },
  { label: "14 days",   value: 14 },
  { label: "30 days",   value: 30 },
]

function IssueKeyPanel({ onClose, onIssued }: { onClose: () => void; onIssued: () => void }) {
  const { secret } = useAdmin()
  const [form, setForm] = useState<IssueKeyRequest>({
    email: "", tier: "pro", name: "", company: "", source: "Direct",
    trial_days: 14, follow_up_date: "", notes: "", send_email: true,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState("")
  const [success, setSuccess] = useState("")

  function set<K extends keyof IssueKeyRequest>(k: K, v: IssueKeyRequest[K]) {
    setForm(f => ({ ...f, [k]: v }))
  }

  async function submit() {
    if (!form.email.trim()) { setError("Email is required"); return }
    setLoading(true); setError("")
    try {
      const res = await adminApi.issueKey(secret, form)
      const emailMsg = res.email_result.sent
        ? " Invite sent."
        : res.email_result.reason === "smtp_not_configured"
        ? " (SMTP not configured — key generated only)"
        : ` (Email failed: ${res.email_result.reason})`
      setSuccess(`Key issued: ${res.key.slice(0, 12)}…${emailMsg}`)
      onIssued()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  const inputCls = "w-full bg-[#060B14] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-[#475569] focus:outline-none focus:border-[#7C3AED]/60"
  const labelCls = "text-[10px] uppercase tracking-wider text-[#94A3B8] mb-1 block"

  return (
    <div className="w-80 shrink-0 border-l border-white/8 bg-[#0D1B2A] flex flex-col">
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
        <span className="text-sm font-bold text-white">Issue New Key</span>
        <button onClick={onClose} className="text-[#94A3B8] hover:text-white"><X size={16} /></button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        <div>
          <label className={labelCls}>Email *</label>
          <input className={inputCls} placeholder="sarah@acme.com" value={form.email}
            onChange={e => set("email", e.target.value)} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Name</label>
            <input className={inputCls} placeholder="Sarah Chen" value={form.name ?? ""}
              onChange={e => set("name", e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>Company</label>
            <input className={inputCls} placeholder="Acme Corp" value={form.company ?? ""}
              onChange={e => set("company", e.target.value)} />
          </div>
        </div>

        <div>
          <label className={labelCls}>Tier *</label>
          <select className={inputCls} value={form.tier} onChange={e => set("tier", e.target.value as IssueKeyRequest["tier"])}>
            {["free","starter","pro","team","enterprise"].map(t => (
              <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Trial Duration</label>
            <select className={inputCls} value={form.trial_days ?? "null"}
              onChange={e => set("trial_days", e.target.value === "null" ? null : Number(e.target.value) as 7|14|30)}>
              {TRIAL_OPTIONS.map(o => (
                <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>Source</label>
            <select className={inputCls} value={form.source ?? "Direct"}
              onChange={e => set("source", e.target.value)}>
              {SOURCES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className={labelCls}>Follow-up Date</label>
          <input type="date" className={inputCls} value={form.follow_up_date ?? ""}
            onChange={e => set("follow_up_date", e.target.value)} />
        </div>

        <div>
          <label className={labelCls}>Notes</label>
          <textarea className={`${inputCls} h-20 resize-none`} placeholder="Met at NYC meetup…"
            value={form.notes ?? ""} onChange={e => set("notes", e.target.value)} />
        </div>

        <div className="bg-[#060B14] rounded-lg p-3 border border-white/6">
          <label className={labelCls}>Send email?</label>
          <div className="flex gap-2">
            <button
              onClick={() => set("send_email", true)}
              className={`flex-1 text-xs py-2 rounded-md border transition-colors ${form.send_email ? "bg-[#7C3AED]/20 border-[#7C3AED]/60 text-violet-300" : "border-white/10 text-[#94A3B8]"}`}>
              ✉ Send invite
            </button>
            <button
              onClick={() => set("send_email", false)}
              className={`flex-1 text-xs py-2 rounded-md border transition-colors ${!form.send_email ? "bg-white/8 border-white/20 text-white" : "border-white/10 text-[#94A3B8]"}`}>
              Generate only
            </button>
          </div>
        </div>

        {error   && <p className="text-xs text-red-400">{error}</p>}
        {success && <p className="text-xs text-emerald-400">{success}</p>}
      </div>

      <div className="px-5 py-4 border-t border-white/8">
        <button
          onClick={submit}
          disabled={loading}
          className="w-full bg-[#7C3AED] hover:bg-[#6D28D9] disabled:opacity-50 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
          {loading ? "Issuing…" : "Issue Key →"}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add "Issue Key" button and panel to the page**

Find the main page component (the `export default function` that renders the licenses page). Locate the header bar that contains the search input and other filters. 

First, add state near the top of the component:
```typescript
const [showIssuePanel, setShowIssuePanel] = useState(false)
```

Then find the "Download" or action button in the header bar area and add the Issue Key button next to it:
```typescript
<button
  onClick={() => setShowIssuePanel(p => !p)}
  className="flex items-center gap-2 bg-[#7C3AED] hover:bg-[#6D28D9] text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors">
  <Plus size={15} />
  Issue Key
</button>
```

Then wrap the main content area and the panel in a flex container. Find where the scrollable table area is rendered and wrap it like:

```typescript
<div className="flex flex-1 min-h-0">
  <div className="flex-1 overflow-auto">
    {/* existing table content */}
  </div>
  {showIssuePanel && (
    <IssueKeyPanel
      onClose={() => setShowIssuePanel(false)}
      onIssued={() => { setShowIssuePanel(false); refetch() }}
    />
  )}
</div>
```

Where `refetch` is whatever function the page uses to reload the licenses list.

- [ ] **Step 3: Add name/company sub-text and expires_at to table rows**

Find where each license row is rendered in the table. It currently shows the masked key. Update to show name/company below the key:

```typescript
<div>
  <p className="font-mono text-xs text-sky-400">{maskKey(lic.key)}</p>
  {(lic.name || lic.company) && (
    <p className="text-[10px] text-[#64748B] mt-0.5">
      {[lic.name, lic.company].filter(Boolean).join(" · ")}
    </p>
  )}
</div>
```

Find the table header and add an "Expires" column. In the corresponding row cell:
```typescript
<td className="px-4 py-3 text-sm">
  {lic.expires_at ? (
    <span className={isExpiringSoon(lic.expires_at) ? "text-amber-400" : lic.expires_at < new Date().toISOString() ? "text-red-400" : "text-[#94A3B8]"}>
      {fmtDateOrDash(lic.expires_at)}
    </span>
  ) : (
    <span className="text-[#475569]">—</span>
  )}
</td>
```

- [ ] **Step 4: Build check**

```bash
cd C:/Users/aware/bots/pushkey/web
npm run build 2>&1 | tail -30
```

Expected: no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/admin/licenses/page.tsx
git commit -m "feat: add IssueKeyPanel to licenses page with CRM fields and send-email toggle"
```

---

## Task 4: Contacts page

**Files:**
- Create: `web/src/app/admin/contacts/page.tsx`

- [ ] **Step 1: Create the contacts page**

Create `web/src/app/admin/contacts/page.tsx` with the full content:

```typescript
"use client"
import { useEffect, useState, useCallback } from "react"
import { Users, Mail, Key, Calendar, ChevronDown, ChevronUp } from "lucide-react"
import { adminApi, type Contact, type ContactKey, maskKey, fmtDateOrDash, isOverdue } from "@/lib/admin-api"
import { useAdmin } from "../_context"

const STAGE_CFG: Record<string, { label: string; dot: string; text: string; bg: string; border: string }> = {
  trial:     { label: "Trial",     dot: "bg-violet-400", text: "text-violet-300", bg: "bg-violet-900/30", border: "border-violet-700/50" },
  active:    { label: "Active",    dot: "bg-emerald-400", text: "text-emerald-300", bg: "bg-emerald-900/20", border: "border-emerald-700/40" },
  converted: { label: "Converted", dot: "bg-emerald-400", text: "text-emerald-300", bg: "bg-emerald-900/20", border: "border-emerald-700/40" },
  churned:   { label: "Churned",   dot: "bg-slate-400",   text: "text-slate-400",   bg: "bg-slate-800/30",  border: "border-slate-700/40" },
  cold:      { label: "Cold",      dot: "bg-slate-500",   text: "text-slate-500",   bg: "bg-slate-900/20",  border: "border-slate-700/30" },
  "":        { label: "Unknown",   dot: "bg-slate-500",   text: "text-slate-400",   bg: "bg-slate-900/20",  border: "border-slate-700/30" },
}

const TIER_ICONS: Record<string, string> = {
  free: "🔲", starter: "🚀", pro: "⚡", team: "👥", enterprise: "🏛️",
}

function StageBadge({ stage }: { stage: string }) {
  const c = STAGE_CFG[stage] ?? STAGE_CFG[""]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${c.bg} ${c.text} ${c.border}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {c.label}
    </span>
  )
}

function KeyHistory({ keys }: { keys: ContactKey[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {keys.map(k => (
        <div key={k.key} className="bg-[#060B14] rounded-md px-2.5 py-1.5 border border-white/6 text-xs flex items-center gap-2">
          <span>{TIER_ICONS[k.tier] ?? "🔑"}</span>
          <span className="font-mono text-sky-400">{maskKey(k.key)}</span>
          <span className="text-[#475569]">·</span>
          <span className={k.status === "active" ? "text-emerald-400" : k.status === "revoked" ? "text-red-400" : "text-amber-400"}>
            {k.status}
          </span>
          {k.expires_at && (
            <>
              <span className="text-[#475569]">·</span>
              <span className={k.expires_at < new Date().toISOString() ? "text-red-400" : "text-[#94A3B8]"}>
                exp {fmtDateOrDash(k.expires_at)}
              </span>
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function ContactCard({ contact, secret, onUpdated }: { contact: Contact; secret: string; onUpdated: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [editStage, setEditStage] = useState(false)
  const [stage, setStage] = useState(contact.stage)
  const overdue = isOverdue(contact.follow_up_date)
  const initial = (contact.name || contact.email).charAt(0).toUpperCase()
  const borderColor = overdue ? "border-amber-600/50" : contact.stage === "converted" ? "border-emerald-700/40" : "border-white/8"
  const leftBar = overdue ? "bg-amber-500" : contact.stage === "converted" ? "bg-emerald-500" : "bg-[#1E293B]"

  async function saveStage(s: string) {
    await adminApi.updateContact(secret, contact.email, { stage: s })
    setStage(s)
    setEditStage(false)
    onUpdated()
  }

  return (
    <div className={`bg-[#0D1B2A] border ${borderColor} rounded-xl overflow-hidden`}>
      <div className={`flex`}>
        <div className={`w-1 shrink-0 ${leftBar}`} />
        <div className="flex-1 p-4">
          {/* Header row */}
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-[#1E293B] flex items-center justify-center text-sm font-bold text-[#94A3B8] shrink-0">
                {initial}
              </div>
              <div>
                <p className="text-sm font-semibold text-white">{contact.name || contact.email}</p>
                <p className="text-xs text-[#64748B]">
                  {contact.email}{contact.company ? ` · ${contact.company}` : ""}
                </p>
                {contact.source && (
                  <p className="text-[10px] text-[#475569] mt-0.5">Source: {contact.source}</p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {overdue && contact.follow_up_date && (
                <span className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px] font-semibold px-2 py-1 rounded-full">
                  ⚠ Follow-up {fmtDateOrDash(contact.follow_up_date)}
                </span>
              )}
              {editStage ? (
                <select
                  autoFocus
                  value={stage}
                  onChange={e => saveStage(e.target.value)}
                  onBlur={() => setEditStage(false)}
                  className="text-xs bg-[#060B14] border border-white/10 rounded-md px-2 py-1 text-white"
                >
                  {Object.keys(STAGE_CFG).filter(s => s !== "").map(s => (
                    <option key={s} value={s}>{STAGE_CFG[s].label}</option>
                  ))}
                </select>
              ) : (
                <button onClick={() => setEditStage(true)} title="Change stage">
                  <StageBadge stage={stage} />
                </button>
              )}
            </div>
          </div>

          {/* Key history */}
          <div className="mt-3">
            <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-2">Key History</p>
            <KeyHistory keys={contact.keys} />
          </div>

          {/* Notes */}
          {contact.notes && (
            <p className="mt-3 text-xs text-[#94A3B8] italic">&quot;{contact.notes}&quot;</p>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/6">
            <button
              onClick={() => { /* open send email modal - future */ }}
              className="text-xs text-[#94A3B8] hover:text-white flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors">
              <Mail size={12} /> Send email
            </button>
            <button
              onClick={() => setExpanded(e => !e)}
              className="text-xs text-[#94A3B8] hover:text-white flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors ml-auto">
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {expanded ? "Less" : "Details"}
            </button>
          </div>

          {/* Expanded details */}
          {expanded && (
            <div className="mt-3 pt-3 border-t border-white/6 grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-1">Follow-up</p>
                <p className={overdue ? "text-amber-400" : "text-[#94A3B8]"}>
                  {fmtDateOrDash(contact.follow_up_date)}
                </p>
              </div>
              <div>
                <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-1">Last Active</p>
                <p className="text-[#94A3B8]">{fmtDateOrDash(contact.latest_activity)}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function ContactsPage() {
  const { secret } = useAdmin()
  const [contacts, setContacts] = useState<Contact[]>([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState("")
  const [filter, setFilter]     = useState<"all" | "follow-up">("all")

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setContacts(await adminApi.getContacts(secret))
    } finally {
      setLoading(false)
    }
  }, [secret])

  useEffect(() => { load() }, [load])

  const today = new Date().toISOString().slice(0, 10)
  const visible = contacts.filter(c => {
    const matchSearch = !search || [c.email, c.name, c.company].some(
      f => f?.toLowerCase().includes(search.toLowerCase())
    )
    const matchFilter = filter === "all" || (c.follow_up_date && c.follow_up_date <= today)
    return matchSearch && matchFilter
  })

  const overdueCount = contacts.filter(c => c.follow_up_date && c.follow_up_date <= today).length

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="bg-[#0D1B2A] border-b border-white/8 px-6 py-4 flex items-center gap-4">
        <div className="flex items-center gap-2 flex-1">
          <Users size={16} className="text-[#00DC82]" />
          <h1 className="text-sm font-bold text-white">Contacts</h1>
          <span className="text-xs text-[#64748B] ml-2">{contacts.length} total</span>
        </div>
        <div className="flex items-center gap-3">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search…"
            className="bg-[#060B14] border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white placeholder-[#475569] focus:outline-none focus:border-[#7C3AED]/60 w-48"
          />
          <div className="flex gap-1">
            {(["all", "follow-up"] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`text-xs px-3 py-1.5 rounded-md transition-colors ${filter === f ? "bg-white/8 text-white" : "text-[#94A3B8] hover:text-white hover:bg-white/5"}`}>
                {f === "all" ? "All" : `Follow-up due${overdueCount > 0 ? ` (${overdueCount})` : ""}`}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-[#94A3B8] text-sm">Loading…</div>
        ) : visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-[#94A3B8]">
            <Users size={32} className="mb-3 opacity-30" />
            <p className="text-sm">No contacts yet — issue a key to get started</p>
          </div>
        ) : (
          <div className="space-y-3 max-w-3xl">
            {visible.map(c => (
              <ContactCard key={c.email} contact={c} secret={secret} onUpdated={load} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Build check**

```bash
cd C:/Users/aware/bots/pushkey/web
npm run build 2>&1 | tail -30
```

Expected: no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/app/admin/contacts/page.tsx
git commit -m "feat: add Contacts page with card view, stage editing, follow-up filtering"
```

---

## Task 5: Add Contacts nav item to sidebar

**Files:**
- Modify: `web/src/app/admin/layout.tsx`

- [ ] **Step 1: Add Contacts nav item**

Open `web/src/app/admin/layout.tsx`. Find the Operations nav section:

```typescript
{navItem("/admin/licenses", <LayoutGrid size={15} />, "Licenses", stats?.total_active)}
{navItem(
  "/admin/revoked",
  ...
```

Add Contacts after the Licenses item:

```typescript
{navItem("/admin/licenses", <LayoutGrid size={15} />, "Licenses", stats?.total_active)}
{navItem("/admin/contacts", <Users size={15} />, "Contacts")}
{navItem(
  "/admin/revoked",
```

`Users` is already imported from lucide-react (line 8 of the existing file).

- [ ] **Step 2: Build and verify**

```bash
cd C:/Users/aware/bots/pushkey/web
npm run build 2>&1 | tail -20
```

Expected: clean build.

Start dev server and verify:
```bash
cd C:/Users/aware/bots/pushkey/web
npm run dev
```

Open `http://localhost:3000/admin` → login → verify "Contacts" appears in sidebar → click it → page loads (empty state if no contacts yet).

- [ ] **Step 3: Commit**

```bash
git add web/src/app/admin/layout.tsx
git commit -m "feat: add Contacts nav item to admin sidebar"
```

---

## Task 6: End-to-end smoke test

- [ ] **Step 1: Start backend + frontend**

Terminal 1:
```bash
cd C:/Users/aware/bots/pushkey
uvicorn pushkey_cloud_api:app --host 0.0.0.0 --port 8000 --reload
```

Terminal 2:
```bash
cd C:/Users/aware/bots/pushkey/web
npm run dev
```

- [ ] **Step 2: Issue a key via the UI**

1. Open `http://localhost:3000/admin` → login
2. Go to Licenses → click "Issue Key"
3. Fill: email `demo@test.com`, name `Demo User`, tier Pro, trial 14 days, source Twitter, notes `test entry`
4. Click "Generate only" → click "Issue Key →"
5. Verify: success message appears, panel closes, new row appears in table with `Demo User` sub-text and expiry date

- [ ] **Step 3: Verify Contacts page**

1. Click "Contacts" in sidebar
2. Verify `demo@test.com` appears as a contact card
3. Verify key history shows the Pro trial key
4. Click the stage badge → change to "converted" → verify it saves

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: license CRM feature complete — issue, contacts, email flow"
```
