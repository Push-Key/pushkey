"""
Pushkey — vault I/O and encrypted config.
"""
import json
import os
import secrets
from datetime import datetime

import pushkey_shared as _s
from pushkey_crypto import (
    AESGCM,
    _V2_MAGIC,
    _V3_MAGIC,
    _config_key,
    _deserialize_vault,
    _migrate_vault,
    _serialize_vault,
    decrypt_data,
    decrypt_data_v3,
    encrypt_data,
    encrypt_data_v3,
    derive_key,
    log_event,
)


def load_vault(password) -> tuple:
    """Returns (vault_dict, vault_key). vault_key is None for V2/legacy vaults."""
    if not _s.VAULT_FILE.exists():
        return {}, None
    try:
        raw = _s.VAULT_FILE.read_bytes()
        if raw.startswith(_V3_MAGIC):
            plaintext, vault_key = decrypt_data_v3(raw, password=password)
            data = json.loads(plaintext)
        else:
            is_legacy = not raw.startswith(_V2_MAGIC)
            plaintext = decrypt_data(raw, password)
            data = json.loads(plaintext)
            vault_key = None
            if is_legacy:
                log_event("vault upgraded to AES-256-GCM + Argon2id")
        data = _migrate_vault(data)
        vault = _deserialize_vault(data)
        return vault, vault_key
    except ValueError:
        return None, None
    except Exception as e:
        raise ValueError(f"corrupted:{e}")


def save_vault(vault, password, *, vault_key=None, recovery_code=None):
    """Save vault. For V3: pass vault_key (preserve existing key) or recovery_code (create new V3)."""
    import shutil
    _s.ensure_vault_dir()
    payload = _serialize_vault(vault)
    json_str = json.dumps(payload, indent=2)

    if recovery_code is not None:
        encrypted = encrypt_data_v3(json_str, password, recovery_code)
    elif vault_key is not None:
        # Re-encrypt V3 body preserving the existing recovery slot
        existing = _s.VAULT_FILE.read_bytes() if _s.VAULT_FILE.exists() else None
        if existing and existing.startswith(_V3_MAGIC):
            import secrets as _sec
            p = existing[4:]
            salt      = p[0:32]
            rec_salt  = p[32:64]
            rec_nonce = p[124:136]
            rec_ct    = p[136:184]

            pw_key = derive_key(password, salt)
            pw_nonce = _sec.token_bytes(12)
            pw_ct = AESGCM(pw_key).encrypt(pw_nonce, vault_key, None)

            body_nonce = _sec.token_bytes(12)
            body_ct = AESGCM(vault_key).encrypt(body_nonce, json_str.encode(), None)

            encrypted = (
                _V3_MAGIC + salt + rec_salt
                + pw_nonce + pw_ct
                + rec_nonce + rec_ct
                + body_nonce + body_ct
            )
        else:
            encrypted = encrypt_data(json_str, password)
    else:
        encrypted = encrypt_data(json_str, password)

    tmp = _s.VAULT_FILE.with_suffix('.tmp')
    tmp.write_bytes(encrypted)
    os.replace(str(tmp), str(_s.VAULT_FILE))
    try:
        os.chmod(_s.VAULT_FILE, 0o600)
    except Exception:
        pass
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = _s.VAULT_DIR / f"vault_backup_{ts}.enc"
        shutil.copy2(str(_s.VAULT_FILE), str(backup))
        backups = sorted(_s.VAULT_DIR.glob("vault_backup_*.enc"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[3:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def load_config():
    if not _s.CONFIG_FILE.exists():
        return {"projects": {}}
    raw = _s.CONFIG_FILE.read_bytes()
    if raw.lstrip()[:1] == b"{":
        try:
            data = json.loads(raw)
            save_config(data)
            return data
        except Exception:
            pass
        return {"projects": {}}
    try:
        key = _config_key()
        nonce, ct = raw[:12], raw[12:]
        plaintext = AESGCM(key).decrypt(nonce, ct, None)
        return json.loads(plaintext)
    except Exception:
        return {"projects": {}}


def save_config(config):
    _s.ensure_vault_dir()
    key = _config_key()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(config, indent=2).encode(), None)
    tmp = _s.CONFIG_FILE.with_suffix(".tmp")
    tmp.write_bytes(nonce + ct)
    os.replace(str(tmp), str(_s.CONFIG_FILE))
