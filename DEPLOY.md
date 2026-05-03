# Pushkey Deployment Guide

Two services to deploy:
1. **Cloud API** (FastAPI / Python) — license backend + admin endpoints
2. **Admin frontend** (Next.js) — admin console UI

---

## 1. Cloud API

### Option A: Fly.io (recommended)

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login
fly launch --copy-config           # uses fly.toml
fly volumes create pushkey_data --size 1
fly secrets set \
    PUSHKEY_ADMIN_SECRET="YourStrongSecret" \
    PUSHKEY_JWT_SECRET="$(openssl rand -hex 32)" \
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
railway variables set PUSHKEY_ADMIN_SECRET="YourStrongSecret"
# … repeat for each var in .env.example
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
- [ ] `PUSHKEY_ADMIN_SECRET` rotated from default
- [ ] SMTP working — verify via `/admin/settings` test-send
- [ ] Custom domain pointing to API (e.g. `api.pushkey.app`)
- [ ] Admin frontend deployed with correct `NEXT_PUBLIC_ADMIN_API_URL`
- [ ] CORS `ADMIN_ORIGIN` matches admin frontend URL
- [ ] Volume mounted at `/data` so `licenses.json` and `events.jsonl` persist
- [ ] Desktop app rebuilt with `PUSHKEY_SERVER` baked in
- [ ] Generate a test license, activate from desktop, verify heartbeat lands

---

## 6. Backup

Volume contains:
- `licenses.json` — all customer license records (CRM data)
- `users.json` — registered cloud sync users
- `events.jsonl` — append-only event log
- `vaults/*.enc` — encrypted vault blobs (zero-knowledge — server can't read)

Schedule daily volume snapshots via your platform's snapshot feature.
