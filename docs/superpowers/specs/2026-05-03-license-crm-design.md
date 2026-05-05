# License CRM & Key Issuance Design Spec
Date: 2026-05-03

## Problem

The admin console can generate and revoke license keys but has no way to issue a key to a specific person by email, track who has keys, follow up with leads, or see a contact's key history. It's a key management tool, not a CRM.

## Goal

Add a key-issuance CRM flow to the admin dashboard: issue a key to someone by email (with optional auto-invite email), track contact details and sales stage, and view a contacts page that groups licenses by person showing full key history.

---

## Data Model

Extend each license record in `licenses.json` with 6 new CRM fields:

```json
{
  "key": "PRO-XXXXXXXX-XXXXXXXXXXXXXXXX-XXXX",
  "tier": "pro",
  "email": "sarah@acme.com",
  "platform": "",
  "activated": "2026-05-03T00:00:00",
  "last_heartbeat": null,
  "status": "active",
  "notes": "Met at NYC meetup",
  "name": "Sarah Chen",
  "company": "Acme Corp",
  "source": "Twitter",
  "follow_up_date": "2026-05-17",
  "expires_at": "2026-05-17T00:00:00",
  "stage": "trial",
  "sent_invite": true
}
```

**New fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Contact full name |
| `company` | string | Company or org |
| `source` | string | How they found you: `Twitter`, `ProductHunt`, `Referral`, `Direct`, `Conference`, `Other` |
| `follow_up_date` | ISO date string or null | Date to follow up |
| `expires_at` | ISO datetime string or null | Auto-expiry time. null = no expiry (paid keys) |
| `stage` | enum | `trial` / `active` / `converted` / `churned` / `cold` |
| `sent_invite` | boolean | Whether invite email was sent |

Existing records without these fields remain valid — they render with empty/null values in the UI. No migration needed.

---

## Backend (`pushkey_cloud_api.py`)

### New endpoints

**`POST /api/admin/licenses/issue`**

Issues a key with full CRM metadata. Replaces the bare `generate` endpoint for the UI (generate stays for backwards compat).

Request body:
```json
{
  "email": "sarah@acme.com",
  "tier": "pro",
  "name": "Sarah Chen",
  "company": "Acme Corp",
  "source": "Twitter",
  "trial_days": 14,
  "follow_up_date": "2026-05-17",
  "notes": "Met at NYC meetup",
  "send_email": true
}
```

- `trial_days`: 7 / 14 / 30 / null (null = no expiry). Sets `expires_at = now + trial_days`.
- `send_email`: if true and SMTP configured, sends invite email. If false or SMTP not configured, key is generated only.
- Sets `stage = "trial"` if `trial_days` is set, else `stage = "active"`.
- Returns the full license record.

**`GET /api/admin/contacts`**

Returns contacts grouped by email. Each entry contains contact metadata and the full list of their license keys with status.

Response:
```json
[
  {
    "email": "sarah@acme.com",
    "name": "Sarah Chen",
    "company": "Acme Corp",
    "source": "Twitter",
    "follow_up_date": "2026-05-17",
    "stage": "trial",
    "notes": "Met at NYC meetup",
    "keys": [
      {"key": "PRO-...", "tier": "pro", "status": "active", "expires_at": "...", "activated": "..."}
    ],
    "latest_activity": "2026-05-03T00:00:00"
  }
]
```

Sorted by: follow-up due first, then by latest_activity descending.

**`PATCH /api/admin/contacts/{email}`**

Update CRM fields for all licenses belonging to an email address.

Request body (all optional):
```json
{
  "name": "Sarah Chen",
  "company": "Acme Corp",
  "follow_up_date": "2026-05-24",
  "stage": "converted",
  "notes": "Upgraded to Pro"
}
```

Updates all license records for that email with the provided fields.

**`POST /api/admin/licenses/{key}/send-invite`**

Resend the invite email for an existing key.

### Email sending

Implemented via Python `smtplib` (stdlib — no new dependencies).

**Env vars:**
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=app-password
FROM_EMAIL=you@gmail.com
APP_URL=https://pushkey.app
```

If `SMTP_HOST` is not set, `send_email` requests succeed silently with `{"sent": false, "reason": "smtp_not_configured"}`.

**Email template** (plain text + HTML):
```
Subject: Your Pushkey [Tier] access key

Hi [Name],

Here's your Pushkey [Tier] license key:

  [KEY]

To activate:
1. Download Pushkey: [APP_URL]/download
2. Open Settings → License
3. Enter your key

[If trial]: This key expires on [DATE].

Questions? Reply to this email.
```

### Auto-expiry

On each `GET /api/admin/licenses` and `GET /api/admin/contacts` call, check all records with `expires_at` set. If `expires_at < now` and `status == "active"`, set `status = "expired"` and `stage = "churned"`. Write back to file. This is lazy expiry — no background job needed.

---

## Frontend

### `web/src/app/admin/licenses/page.tsx`

**Changes:**
- Add "Issue Key" button in header bar (top right, purple)
- Add `IssueKeyPanel` component: slide-out right panel (320px wide, overlays the table)
  - Fields: Email, Name, Company, Tier (dropdown), Trial Duration (7/14/30/None dropdown), Source (dropdown), Follow-up Date (date input), Notes (textarea)
  - Bottom: "Send invite" / "Generate only" toggle buttons
  - Submit: "Issue Key →" button
  - On success: panel closes, table refreshes, new key row highlighted briefly
- Add columns to table:
  - Sub-text under key: `name · company` (if set)
  - `Expires` column (shows date in amber if within 7 days, red if past)
- Add `source` and `follow_up_date` to the expanded key detail view (if one exists)

### `web/src/app/admin/contacts/page.tsx` (new)

Contact cards layout as designed. Each card shows:
- Avatar initial + name + email + company + source + added date
- Follow-up badge (amber warning if due ≤ today)
- Stage badge (trial / converted / cold etc.)
- Key history list (each key: tier icon + masked key + status + expiry)
- Notes (italic)
- Action buttons: Send email, Issue key (opens licenses panel pre-filled), Edit notes, Set follow-up

Filter bar: search by name/email/company, filter by stage, filter "Follow-up due".

### `web/src/lib/admin-api.ts`

New methods:
```typescript
issueKey(data: IssueKeyRequest): Promise<License>
getContacts(): Promise<Contact[]>
updateContact(email: string, data: Partial<Contact>): Promise<void>
sendInvite(key: string): Promise<{ sent: boolean; reason?: string }>
```

New types: `IssueKeyRequest`, `Contact`.

### `web/src/app/admin/layout.tsx`

Add "Contacts" nav item to sidebar between "Licenses" and "Analytics":
```
🔑 Licenses
👥 Contacts       ← new
📊 Analytics
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| SMTP not configured | Issue succeeds, `sent_invite: false`, UI shows "Key generated — email not sent (SMTP not configured)" |
| SMTP send fails | Issue succeeds (key saved), response includes `sent: false, reason: "smtp_error"`, UI shows warning |
| Duplicate email issue | Allowed — one person can have multiple keys. All appear in contacts history. |
| `trial_days` = null on issue | No `expires_at` set, `stage = "active"` |
| `PATCH /contacts/{email}` for unknown email | 404 |

---

## Files Changed

| File | Change |
|------|--------|
| `pushkey_cloud_api.py` | Add `issue`, `contacts`, `update_contact`, `send_invite` endpoints; add `_send_invite_email()` helper; add lazy auto-expiry to list endpoints |
| `web/src/app/admin/licenses/page.tsx` | Add `IssueKeyPanel` component, update table columns |
| `web/src/app/admin/contacts/page.tsx` | New page — contact cards view |
| `web/src/lib/admin-api.ts` | Add `issueKey`, `getContacts`, `updateContact`, `sendInvite` + types |
| `web/src/app/admin/layout.tsx` | Add Contacts nav item |
