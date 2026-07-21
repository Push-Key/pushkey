# Pushkey Cloud Storage Migration

Status: Phase 4 migration framework and schema baseline.

## Provider Decision

Recommended managed services for the production migration:

- PostgreSQL: Railway Postgres or Neon for the initial hosted deployment.
- Object storage: Cloudflare R2 or AWS S3 for encrypted vault blob versions.

The application must continue treating vault blobs as zero-knowledge ciphertext.
The database stores metadata, constraints, indexes, audit records, account data,
license/device state, and object-storage keys. It must not store plaintext API
keys, master passwords, recovery codes, salts, decrypted vaults, or vault keys.

## Schema Baseline

The migration framework in `pushkey_migrations.py` defines the first relational
schema for:

- users;
- admins;
- sessions;
- licenses;
- devices;
- contacts;
- tickets;
- settings;
- audits;
- vault revisions.

License keys and reset tokens are represented by hash columns. Vault revisions
store object keys, ETags, sizes, and timestamps for encrypted blobs only.

## Migration Process

1. Run migration dry-run and verify the ordered migration list.
2. Apply schema migrations into an empty database.
3. Import the legacy JSON/JSONL/blob dataset into a staging environment.
4. Reconcile record counts and encrypted blob hashes.
5. Run concurrent write tests for license, contact, and vault metadata paths.
6. Verify stale vault revisions cannot overwrite newer revisions.
7. Verify API responses, logs, database rows, and object storage never contain
   plaintext secrets.
8. Run rollback from the previous snapshot before promoting the migration.

## Rollback And Idempotency

- Migration state is tracked by migration name.
- Reapplying already-applied migrations must be a no-op.
- Import dry-runs must not write output files or copy vault blobs.
- Import reports include counts and hashes, not plaintext vault content.
- Production flat-file write paths remain in place until the staged migration
  passes reconciliation and rollback checks.
