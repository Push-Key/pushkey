# Recovery Key Feature — Design Spec
Date: 2026-05-03

## Problem

Vault is AES-256-GCM encrypted with the master password as the sole key. If the master
password is forgotten (or the vault directory changes during development), all keys are
permanently lost. No recovery path exists.

## Goal

Allow users to recover vault access with a recovery code, without storing the master
password anywhere.

## Approach

V3 vault format with key wrapping. A random 32-byte `vault_key` encrypts the vault body.
Two header slots wrap `vault_key` under different credentials: one for the master password,
one for the recovery code. Resetting the password only rewrites the password slot — the
vault body and recovery slot are unchanged.

---

## Crypto Layer

### New format: `PK3\x00`

Binary layout (fixed-size header + variable body):

```
Offset  Size   Field
------  ----   -----
0       4      magic = b'PK3\x00'
4       32     salt          (global salt, same as .salt file — embedded for portability)
36      32     rec_salt      (independent salt for recovery key derivation)
68      12     pw_slot_nonce
80      48     pw_slot_ct    = AESGCM(derive_key(password, salt)).encrypt(pw_slot_nonce, vault_key)
128     12     rec_slot_nonce
140     48     rec_slot_ct   = AESGCM(derive_key(recovery_code, rec_salt)).encrypt(rec_slot_nonce, vault_key)
188     12     body_nonce
200     var    body_ct       = AESGCM(vault_key).encrypt(body_nonce, json_data)
```

Total header size: 200 bytes. `vault_key` = `secrets.token_bytes(32)`, generated once at
vault creation, never written to disk in plaintext.

### Recovery code format

`PUSH-XXXX-XXXX-XXXX-XXXX` — 20 base32 characters = 100 bits of entropy.

Generated via `secrets.token_bytes(13)` → base32 encode → insert dashes. Entry is
normalized (strip whitespace + dashes) before use.

### New functions in `pushkey_crypto.py`

```python
def encrypt_data_v3(data: str, password: str, recovery_code: str) -> bytes:
    """Encrypt data with V3 key-wrapping format."""

def decrypt_data_v3(token: bytes, *, password: str = None, recovery_code: str = None
                    ) -> tuple[str, bytes]:
    """Decrypt V3 vault. Returns (plaintext, vault_key).
    Pass either password or recovery_code, not both."""

def rekey_vault(token: bytes, recovery_code: str, new_password: str) -> bytes:
    """Password reset. Decrypts vault_key via recovery slot, re-wraps under new password."""

def add_recovery_key(token: bytes, password: str, recovery_code: str) -> bytes:
    """Migrate V2 vault to V3 by adding recovery slot. Called from Settings opt-in."""

def generate_recovery_code() -> str:
    """Returns a fresh PUSH-XXXX-XXXX-XXXX-XXXX code."""
```

### Changes to `pushkey_vault.py`

`load_vault` returns `(vault_dict, vault_key_or_None)`:
- V3: returns `(dict, vault_key bytes)`
- V2/legacy: returns `(dict, None)`

`save_vault` accepts optional `vault_key` param. For V3 vaults, re-encrypts body with
the same `vault_key` (not a new one). For V2 vaults, behaviour unchanged.

`decrypt_data` in `pushkey_crypto.py` is unchanged — V3 is a separate code path.

---

## UI Flows

### 1. New vault creation

After master password entry + confirmation in `LoginFrame` (when `is_new=True`), before
`save_vault` is called, open `RecoverySetupDialog`:

- Recovery code displayed in large monospace label with copy button
- Checkbox: "I've written this down somewhere safe"
- Confirm button disabled until checkbox ticked
- On confirm: vault saved as V3 with both slots populated

No way to skip — new vaults always get a recovery slot.

### 2. Forgot password (LoginFrame)

Replace current "Forgot password?" dialog (restore-from-backup) with `ForgotPasswordDialog`:

1. Detect vault format on open:
   - V2/no vault: show old "restore from backup" message (no recovery slot exists)
   - V3: show recovery code entry field
2. User enters recovery code → call `rekey_vault` attempt:
   - Failure (`ValueError("wrong_recovery_code")`): inline error, dialog stays open
   - Success: show new password + confirm fields
3. User sets new password → `rekey_vault` writes new vault bytes → log in normally

### 3. Settings opt-in (existing V2 vaults)

In Security tab, new "Recovery Key" card:

**State: not configured**
- Label: "Recovery Key — Not configured"
- Button: "Set up recovery key"
- Flow: re-auth with current password → show `RecoverySetupDialog` → on confirm,
  call `add_recovery_key` → write V3 vault

**State: configured (V3 vault)**
- Label: "Recovery Key — Active"  
- Button: "Regenerate"
- Regenerate flow: re-auth → show new code → on confirm, call `add_recovery_key`
  (generates new `rec_salt` + new slot)

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Wrong recovery code | `ValueError("wrong_recovery_code")` → inline error in dialog |
| V2 vault on "Forgot password?" | Show "no recovery key — restore from backup" message |
| V3 vault with zeroed rec slot | Treat same as V2 — "no recovery key" message |
| Recovery code with spaces/dashes | Normalize before decrypt (strip + upper) |
| `save_vault` called on V3 without vault_key | Raise — caller must pass vault_key for V3 |

---

## Backward Compatibility

- `decrypt_data(token, password)` unchanged — handles V2 + legacy Fernet
- V2 vaults remain readable and writable without changes
- V3 vaults only created when user explicitly sets up recovery key (new vault wizard
  or Settings opt-in)
- No automatic migration of existing V2 vaults

---

## Files Changed

| File | Change |
|------|--------|
| `pushkey_crypto.py` | Add `_V3_MAGIC`, `generate_recovery_code`, `encrypt_data_v3`, `decrypt_data_v3`, `rekey_vault`, `add_recovery_key` |
| `pushkey_vault.py` | `load_vault` returns `(dict, vault_key)`, `save_vault` accepts `vault_key` |
| `pushkey.py` | `LoginFrame`: new vault wizard calls recovery setup, "Forgot password?" replaced; `AppFrame` Security tab: recovery key card |
| `tests/test_vault_crypto.py` | Tests for V3 round-trip, rekey, wrong code, migration |
