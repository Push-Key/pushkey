# Pushkey Admin Auth And Operations Model

Status: Phase 3 model and operating procedure.

## Admin Identity Model

- Admins are individual accounts, not shared browser secrets.
- Each admin has an immutable actor ID, email, display name, enabled/disabled
  state, role, password hash, MFA state, session list, and audit metadata.
- New password hashes use Argon2id. Legacy bcrypt hashes may verify during
  migration but must be upgraded on successful authentication.
- Roles are deny-by-default. Route permissions should be granted explicitly by
  role and checked through an authenticated principal dependency.

## Session Model

- Login issues short-lived `HttpOnly`, `Secure`, `SameSite` cookies.
- Mutating requests require CSRF validation.
- Sessions must be revocable server-side.
- Password reset, MFA reset, account disablement, suspected compromise, and
  offboarding must revoke active sessions.

## MFA And Recovery Model

- MFA enrollment binds a TOTP secret or future hardware factor to one admin.
- Recovery codes are one-time-use, generated at enrollment, and stored only as
  hashes.
- MFA reset requires an existing privileged admin or break-glass procedure.

## Break-Glass Credential

- A break-glass credential may exist only in the server/platform secret store.
- It must not be shown, stored, or editable in browser JavaScript.
- Use requires incident logging, immediate password rotation, and session
  revocation after the incident.

## Provisioning Procedure

1. Create the admin account from a server-side command or privileged admin API.
2. Assign the least-privilege role needed for the operator's job.
3. Require first-login password change if a temporary password was used.
4. Require MFA enrollment before production mutations are allowed.
5. Record actor ID, creator ID, role, timestamp, and reason in the audit log.

## Offboarding Procedure

1. Disable the admin account.
2. Revoke all active sessions and refresh tokens.
3. Reassign or close owned support/audit workflows.
4. Rotate shared operational credentials if the departing admin had access.
5. Record actor ID, target admin ID, timestamp, IP/request ID, and reason.

## Audit Fields

Admin mutation audit events should include:

- actor ID;
- actor role;
- request ID;
- source IP or trusted proxy identity;
- action;
- target type and target ID;
- outcome; and
- redacted details.
