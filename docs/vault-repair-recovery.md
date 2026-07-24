# Pushkey Vault Repair And Recovery

Status: Phase 2 local recovery procedure.

This procedure is for local vault failures involving `~/.pushkey/vault.enc`.
It does not bypass encryption. Recovery still requires either the master
password or the recovery code.

## What Pushkey Can Recover From

- An interrupted write where a previous rolling backup exists.
- A V1 or V2 vault that can still be decrypted and migrated.
- A V3 vault where either the master-password slot or recovery-code slot still
  unwraps the vault key.
- A damaged current vault when one of the rolling `vault_backup_*.enc` files is
  intact.

## What Pushkey Cannot Recover From

- Loss of both master password and recovery code.
- Corruption of every vault copy and every backup copy.
- A recovery code that was never saved at initialization.
- Plaintext secrets deleted from the vault without any remaining backup or
  provider-side copy.

## Triage Steps

1. Stop Pushkey desktop, local API, CLI REPL, MCP clients, and any process that
   may have the vault open.
2. Copy the entire `~/.pushkey` directory to a separate offline location before
   making changes.
3. Check whether `vault.enc` exists and has nonzero size.
4. List rolling backups named like `vault_backup_*.enc` and sort newest first.
5. Try normal unlock with the master password.
6. If master unlock fails, try recovery-code unlock or rekey.
7. If the current vault is corrupted, copy the newest backup over `vault.enc`
   only after preserving the damaged file for analysis.
8. Unlock the restored vault and immediately rotate any secrets that may have
   been stale or restored from an older backup.

## Verification After Restore

- Run `pushkey list` and confirm expected key names are present.
- Run `pushkey status` and check health counts.
- Open the local app and confirm it unlocks.
- Confirm `health.json` regenerates after a successful save.
- Run project injection only after verifying the restored assignments.

## Operator Notes

- Do not paste production secrets into MCP/plaintext chat while repairing.
- Do not delete damaged vault files until a replacement vault has been
  decrypted successfully.
- Treat restored secrets as potentially stale; rotate provider-side keys after
  recovery where possible.
