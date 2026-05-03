# Security Policy

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Email: security@pushkey.dev

We aim to respond within 48 hours and will coordinate a fix + disclosure timeline with you. We follow responsible disclosure: we'll credit you in the release notes unless you prefer to remain anonymous.

---

## Vault Format Specification

This document is the canonical reference for the Pushkey vault format. It exists so the security community can audit, verify, and independently implement the format.

### File Location

```
~/.pushkey/vault.enc    — encrypted vault
~/.pushkey/.salt        — 32-byte random salt (chmod 600)
```

The salt is created once at vault initialization and never changes. It is used as the KDF input for all password-derived keys.

---

## V3 Vault Format (current)

### Binary Layout

All integers are big-endian. All crypto uses `cryptography` (Python) / BoringSSL under the hood.

```
Offset  Length  Field
──────  ──────  ──────────────────────────────────────────────────────
0       4       Magic: 0x504B3300  ("PK3\x00")
4       32      pw_salt    — random, per-vault, used for master pw KDF
36      32      rec_salt   — random, per-vault, used for recovery code KDF
68      12      pw_nonce   — AES-GCM nonce for password slot
80      48      pw_ct      — AES-GCM(pw_key, vault_key) + 16-byte tag
128     12      rec_nonce  — AES-GCM nonce for recovery slot
140     48      rec_ct     — AES-GCM(rec_key, vault_key) + 16-byte tag
188     12      body_nonce — AES-GCM nonce for vault body
200     variable body_ct   — AES-GCM(vault_key, UTF-8 JSON) + 16-byte tag
```

Total header size: 200 bytes. Body is variable length.

### Key Derivation

Both the master password path and the recovery code path use the same KDF — Argon2id with independent salts.

**Master password:**
```
pw_key = Argon2id(
    secret      = master_password.encode("utf-8"),
    salt        = pw_salt,
    time_cost   = 3,
    memory_cost = 65536,   # 64 MB
    parallelism = 4,
    hash_len    = 32,
    type        = Argon2Type.ID
)
```

**Recovery code:**
```
# Recovery code format: PUSH-XXXX-XXXX-XXXX-XXXX
# Normalized before KDF: strip dashes, uppercase
normalized_code = recovery_code.upper().replace("-", "")

rec_key = Argon2id(
    secret      = normalized_code.encode("utf-8"),
    salt        = rec_salt,
    time_cost   = 3,
    memory_cost = 65536,
    parallelism = 4,
    hash_len    = 32,
    type        = Argon2Type.ID
)
```

**Argon2id unavailable fallback:**
```
key = PBKDF2-HMAC-SHA256(password, salt, iterations=600_000, dklen=32)
```

### Unlock Flow

**Via master password:**
```
1. vault_key  = AES-256-GCM.decrypt(pw_key,  pw_nonce,  pw_ct)
2. plaintext  = AES-256-GCM.decrypt(vault_key, body_nonce, body_ct)
3. vault_dict = JSON.parse(plaintext)
```

**Via recovery code:**
```
1. vault_key  = AES-256-GCM.decrypt(rec_key, rec_nonce, rec_ct)
2. plaintext  = AES-256-GCM.decrypt(vault_key, body_nonce, body_ct)
3. vault_dict = JSON.parse(plaintext)
```

### Password Change (`pushkey passwd`)

Only the password slot is re-encrypted. The recovery slot and body are preserved byte-for-byte:

```
new_pw_key   = Argon2id(new_password, pw_salt, ...)
new_pw_nonce = random_bytes(12)
new_pw_ct    = AES-256-GCM.encrypt(new_pw_key, vault_key)

# rec_salt, rec_nonce, rec_ct, body_nonce, body_ct unchanged
```

### Recovery Code Generation

```python
raw  = secrets.token_bytes(13)          # 104 bits
b32  = base64.b32encode(raw).rstrip("=")[:20].upper()
code = f"PUSH-{b32[0:4]}-{b32[4:8]}-{b32[8:12]}-{b32[12:16]}"
# Effective entropy: ~80 bits (16 base32 chars × 5 bits)
```

---

## V2 Vault Format (legacy, read-only supported)

```
Offset  Length  Field
──────  ──────  ──────────────────────────────────
0       4       Magic: 0x504B3200  ("PK2\x00")
4       12      nonce
16      variable AES-256-GCM(key, UTF-8 JSON) + tag
```

Key derivation: same Argon2id/PBKDF2 as V3, using the single shared `.salt` file.

No recovery slot. Auto-detected on load; user prompted to migrate to V3.

---

## V1 Vault Format (legacy Fernet, auto-migrated)

Detected by absence of `PK2\x00` or `PK3\x00` magic. Uses Fernet (AES-128-CBC + HMAC-SHA256) via the `cryptography` library. PBKDF2-SHA256 at 600,000 iterations. Migrated to V2 on first successful open.

---

## Audit Log Format

```
~/.pushkey/pushkey.log
```

Binary, length-prefixed. Each entry:

```
[4 bytes: big-endian uint32 payload_length]
[12 bytes: AES-GCM nonce]
[payload_length - 12 - 16 bytes: ciphertext]
[16 bytes: AES-GCM authentication tag]
```

The log key is derived from the salt (not the master password):

```
log_key = PBKDF2-HMAC-SHA256(b"pushkey-log-key", salt, iterations=100_000)
```

This allows audit log inspection without the master password — intentionally. If the master password changes, the log remains readable.

---

## Config Encryption

```
~/.pushkey/config.json  (encrypted despite the .json extension)
```

```
[12 bytes: nonce]
[variable: AES-256-GCM(config_key, JSON) + tag]
```

Config key:
```
config_key = PBKDF2-HMAC-SHA256(b"pushkey-config-key", salt, iterations=100_000)
```

---

## Cloud Sync Security Model

The cloud sync backend (`server/`) is zero-knowledge:

- Client encrypts the vault locally before transmission
- Server receives and stores only ciphertext (`vault.enc` contents)
- Server has no access to the master password, salt, or any key material
- TLS in transit, AES-256-GCM at rest on the server side as well

The server cannot decrypt your vault. If the server is compromised, attackers get encrypted blobs that require breaking Argon2id + AES-256-GCM to exploit.

---

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Disk read by another process | Vault + config + log all encrypted at rest; `chmod 600` on sensitive files |
| Weak master password | Argon2id with 64 MB memory cost makes brute-force expensive |
| Forgotten master password | Recovery code (independent Argon2id slot) |
| Lost recovery code + forgotten password | No recovery possible — this is by design |
| Vault file tampering | AES-GCM authentication tag detects any modification |
| Partial write / corruption | Atomic `os.replace()` writes; 3 rolling backups at `vault_backup_*.enc` |
| Cloud server compromise | Zero-knowledge — server stores only ciphertext |
| Key accidentally committed to git | Git scan (Starter+) + `inject` always writes `.gitignore` guard |
| Master password stolen, no physical access | Recovery code cannot be derived from the master password |

---

## What Is NOT In Scope for This Repo

The following are proprietary and not part of the open-core security surface:

- `pushkey_tiers.py` — license gate logic
- `server/` — cloud sync backend (separate private repo)
- `web/` — admin dashboard

Security findings in these components are still welcome via the email above, but they won't be addressed via public PRs.

---

## Supported Versions

| Version | Supported |
|---------|:---------:|
| 2.x (V3 vault) | ✓ |
| 1.x (V2 vault) | read + migrate only |
| < 1.0 (V1 Fernet) | migrate only |
