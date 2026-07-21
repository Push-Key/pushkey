# Pushkey Data Governance

Status: Phase 11 launch-policy draft.

## Data Categories

- Local vault contents stay on the user's machine unless encrypted sync is enabled.
- Cloud sync stores encrypted vault blobs and revision metadata only.
- Account metadata includes email, license tier, device IDs, activation timestamps,
  and support contact records.
- Operational logs may include request IDs, route names, status codes, timing,
  source IP, and redacted error details.
- Admin audit records include actor ID, target ID, action, request ID, timestamp,
  and outcome.

## Retention Targets

- Encrypted vault revisions: retain according to the documented sync retention
  window after the object-storage migration.
- Admin audit records: retain at least one year for security investigation.
- Support tickets and contact requests: retain while the account is active, then
  delete or anonymize under the account deletion workflow.
- Operational logs: retain only as long as needed for debugging, security review,
  and abuse prevention.

## Export And Deletion

- Account export must include account metadata, license/device records, support
  records, and encrypted vault blobs when cloud sync is enabled.
- Account deletion must revoke sessions, invalidate device tokens, remove support
  records where legally permitted, and schedule encrypted vault blobs for
  deletion according to the retention policy.
- Local vault deletion remains user controlled because local files are outside
  the cloud service boundary.

## Subprocessors

- Hosting, object storage, email delivery, payment processing, analytics, and
  error reporting providers must be listed before launch if they process account
  metadata, support data, logs, or encrypted blobs.
- No subprocessor may receive plaintext vault secrets.

## Privacy Policy Coverage Checklist

- Accounts and authentication metadata.
- License, billing, and device activation metadata.
- Support requests and contact forms.
- Encrypted vault blobs and revision metadata.
- Operational logs, audit records, metrics, and error reports.
- Export, deletion, retention, subprocessors, and support contacts.
