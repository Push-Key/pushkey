# Pushkey Deployment Guide

Two services to deploy:
1. **Cloud API** (`pushkey_cloud_api.py`, FastAPI / Python). License backend and admin endpoints.
2. **Admin frontend** (Next.js). Admin console UI.

---

## 1. Cloud API

### Option A: Fly.io (recommended)

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login
fly launch --copy-config           # uses fly.toml
fly volumes create pushkey_data --size 1
fly secrets set \
    PUSHKEY_ADMIN_EMAIL="admin@example.com" \
    PUSHKEY_ADMIN_PASSWORD="$(openssl rand -base64 36)" \
    PUSHKEY_JWT_SECRET="$(openssl rand -hex 32)" \
    PUSHKEY_ADMIN_SESSION_TTL_MIN="30" \
    PUSHKEY_ADMIN_COOKIE_SECURE="true" \
    SMTP_HOST="smtp.gmail.com" \
    SMTP_PORT="587" \
    SMTP_USER="you@example.com" \
    SMTP_PASS="your-app-password" \
    FROM_EMAIL="you@example.com" \
    APP_URL="https://pushkey.app" \
    ADMIN_ORIGIN="https://admin.pushkey.app"
fly deploy
```

### Option B: Railway

```bash
railway login
railway init
railway add --service pushkey-api
railway variables set PUSHKEY_ADMIN_EMAIL="admin@example.com"
railway variables set PUSHKEY_ADMIN_PASSWORD="<generated-password>"
railway variables set PUSHKEY_JWT_SECRET="<generated-64-hex-secret>"
# Repeat for each required variable in .env.example.
railway up
```

### Option C: Self-host with Docker

```bash
docker build -t pushkey-api .
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/data:/data \
  --env-file .env \
  pushkey-api
```

---

## 2. Admin Frontend (Next.js)

### Vercel (recommended)

```bash
cd web
vercel link
vercel env add NEXT_PUBLIC_ADMIN_API_URL production
# Enter: https://pushkey-api.fly.dev
vercel --prod
```

### Self-host

```bash
cd web
npm run build
NEXT_PUBLIC_ADMIN_API_URL="https://pushkey-api.fly.dev" npm start
```

---

## 3. Desktop App Configuration

Once the cloud API is deployed, rebuild Pushkey desktop with the new server URL:

```powershell
# Set permanent env var on dev machine
[Environment]::SetEnvironmentVariable("PUSHKEY_SERVER", "https://pushkey-api.fly.dev", "User")

# Rebuild
python build_exe.py
```

The new `.exe` will hit your production API for activation/heartbeat.

---

## 4. SMTP Setup (Gmail example)

1. Enable 2FA on your Google account
2. Generate an "App Password" at https://myaccount.google.com/apppasswords
3. Use that 16-char password as `SMTP_PASS` (not your regular password)

For other providers (SendGrid, Mailgun, AWS SES), use their SMTP relay credentials.

---

## 5. First-time setup checklist

- [ ] Cloud API deployed with all env vars set
- [ ] `PUSHKEY_ADMIN_EMAIL` identifies the bootstrap administrator
- [ ] `PUSHKEY_ADMIN_PASSWORD` is randomly generated and stored only in the platform secret store
- [ ] `PUSHKEY_ADMIN_COOKIE_SECURE=true` and both services use HTTPS
- [ ] SMTP working. Verify via `/admin/settings` test-send
- [ ] Custom domain pointing to API (e.g. `api.pushkey.app`)
- [ ] Admin frontend deployed with correct `NEXT_PUBLIC_ADMIN_API_URL`
- [ ] CORS `ADMIN_ORIGIN` matches admin frontend URL
- [ ] Volume mounted at `/data` so JSON compatibility storage persists
- [ ] Exactly one API worker and one machine must remain running until Phase 4 database migration
- [ ] Desktop app rebuilt with `PUSHKEY_SERVER` baked in
- [ ] Generate a test license, activate from desktop, verify heartbeat lands

---

## 6. Backup

Volume contains:
- `licenses.json`. All customer license records and device state.
- `admins.json`. Bootstrap administrator record with a password hash.
- `admin_sessions.json`. Revocable administrator sessions.
- `users.json`. Registered cloud sync users.
- `events.jsonl`. Append-only event log.
- `vaults/*.enc`. Encrypted vault blobs. The server cannot decrypt them.

Schedule daily volume snapshots via your platform's snapshot feature.
