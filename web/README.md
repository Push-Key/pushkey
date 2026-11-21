# PushKey Web Operator Runbook

This Next.js app contains the public website, docs, customer portal, and admin
console for PushKey.

## Environment

- `NEXT_PUBLIC_SITE_URL`: canonical public origin, defaults to
  `https://push-key.com`.
- `NEXT_PUBLIC_ADMIN_API_URL`: cloud/admin API origin, defaults in client code
  to `http://localhost:8000`.
- `NEXT_PUBLIC_STRIPE_PRO_MONTHLY`, `NEXT_PUBLIC_STRIPE_PRO_ANNUAL`,
  `NEXT_PUBLIC_STRIPE_TEAM_MONTHLY`, `NEXT_PUBLIC_STRIPE_TEAM_ANNUAL`,
  `NEXT_PUBLIC_STRIPE_LIFETIME`: optional payment links.

## Local Development

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`.

## Verification

```powershell
npm run lint
npm run build
```

The production build generates metadata routes for `sitemap.xml` and
`robots.txt`, plus explicit not-found and error pages.

## Deployment Notes

- Keep public feature claims aligned with `docs/ALPHA_SELLABLE_READINESS_CHECKLIST.md`.
- Do not expose unfinished admin tools in the authenticated navigation.
- Set `NEXT_PUBLIC_ADMIN_API_URL` to the deployed canonical cloud API before
  publishing the admin console.
- Keep `/admin/` disallowed in `robots.ts`.
