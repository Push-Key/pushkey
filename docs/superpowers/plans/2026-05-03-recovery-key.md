# Recovery Key Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recovery-key feature so users can reset their master password without losing vault data.

**Architecture:** Introduce a V3 vault format (`PK3\x00`) with key-wrapping: a random `vault_key` encrypts the body; two header slots wrap `vault_key` under the master password and a recovery code respectively. Password reset rewrites only the password slot. V2 vaults are unaffected until the user opts in from Settings.

**Tech Stack:** Python, `cryptography` (AESGCM, already imported), `secrets`, `base64`, `customtkinter` (UI).

---

## File Map

| File | Change |
|------|--------|
| `pushkey_crypto.py` | Add `_V3_MAGIC`, `generate_recovery_code`, `encrypt_data_v3`, `decrypt_data_v3`, `rekey_vault`, `add_recovery_key` |
| `pushkey_vault.py` | `load_vault` returns `(dict, vault_key_or_None)`; `save_vault` accepts optional `vault_key` |
| `pushkey.py` | Update `load_vault` callers; new vault wizard calls `RecoverySetupDialog`; replace `_show_restore_hint` with `ForgotPasswordDialog`; add recovery key card to `render_scan` |
| `tests/test_vault_crypto.py` | V3 round-trip, rekey, wrong recovery code, V2→V3 migration |

---

## Task 1: V3 crypto primitives in `pushkey_crypto.py`

**Files:**
- Modify: `pushkey_crypto.py`
- Test: `tests/test_vault_crypto.py`

### V3 binary layout (header = 200 bytes fixed):

```
Offset  Size  Field
0       4     magic b'PK3\x00'
4       32    salt (global salt)
36      32    rec_salt (independent recovery salt)
68      12    pw_slot_nonce
80      48    pw_slot_ct   = AESGCM(derive_key(password, salt)).encrypt(nonce, vault_key, None)
128     12    rec_slot_nonce
140     48    rec_slot_ct  = AESGCM(derive_key(norm_code, rec_salt)).encrypt(nonce, vault_key, None)
188     12    body_nonce
200+    var   body_ct      = AESGCM(vault_key).encrypt(nonce, data.encode(), None)
```

`vault_key` = 32 bytes → AES-GCM tag = 16 bytes → slot_ct = 48 bytes. ✓

- [ ] **Step 1: Write failing tests**

Add to `tests/test_vault_crypto.py`:

```python
import pytest
from pushkey_crypto import (
    generate_recovery_code,
    encrypt_data_v3,
    decrypt_data_v3,
    rekey_vault,
    add_recovery_key,
    _V3_MAGIC,
    encrypt_data,
    decrypt_data,
)

# ── generate_recovery_code ─────────────────────────────────────────────────────

def test_recovery_code_format():
    code = generate_recovery_code()
    assert code.startswith("PUSH-")
    parts = code.split("-")
    assert len(parts) == 5
    assert all(len(p) == 4 for p in parts[1:])

def test_recovery_code_unique():
    assert generate_recovery_code() != generate_recovery_code()

# ── V3 round-trip ──────────────────────────────────────────────────────────────

def test_v3_round_trip(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("hello vault", "mypassword", code)
    assert token.startswith(_V3_MAGIC)

    plaintext, vault_key = decrypt_data_v3(token, password="mypassword")
    assert plaintext == "hello vault"
    assert len(vault_key) == 32

def test_v3_decrypt_with_recovery_code(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("secret data", "hunter2", code)

    plaintext, vault_key = decrypt_data_v3(token, recovery_code=code)
    assert plaintext == "secret data"
    assert len(vault_key) == 32

def test_v3_wrong_password_raises(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("data", "correct", code)
    with pytest.raises(ValueError, match="wrong_password"):
        decrypt_data_v3(token, password="wrong")

def test_v3_wrong_recovery_code_raises(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("data", "pw", code)
    with pytest.raises(ValueError, match="wrong_recovery_code"):
        decrypt_data_v3(token, recovery_code="PUSH-AAAA-BBBB-CCCC-DDDD")

# ── rekey_vault ────────────────────────────────────────────────────────────────

def test_rekey_vault_changes_password(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("my keys", "oldpass", code)

    new_token = rekey_vault(token, code, "newpass")

    plaintext, _ = decrypt_data_v3(new_token, password="newpass")
    assert plaintext == "my keys"

def test_rekey_vault_old_password_fails(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("my keys", "oldpass", code)
    new_token = rekey_vault(token, code, "newpass")

    with pytest.raises(ValueError):
        decrypt_data_v3(new_token, password="oldpass")

def test_rekey_recovery_code_still_works(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()
    token = encrypt_data_v3("my keys", "oldpass", code)
    new_token = rekey_vault(token, code, "newpass")

    plaintext, _ = decrypt_data_v3(new_token, recovery_code=code)
    assert plaintext == "my keys"

# ── add_recovery_key (V2 → V3 migration) ─────────────────────────────────────

def test_add_recovery_key_migrates_v2(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    v2_token = encrypt_data("original data", "mypass")
    code = generate_recovery_code()
    v3_token = add_recovery_key(v2_token, "mypass", code)

    assert v3_token.startswith(_V3_MAGIC)
    plaintext, _ = decrypt_data_v3(v3_token, password="mypass")
    assert plaintext == "original data"

    plaintext2, _ = decrypt_data_v3(v3_token, recovery_code=code)
    assert plaintext2 == "original data"

# ── recovery code normalization ────────────────────────────────────────────────

def test_recovery_code_normalization(tmp_path, monkeypatch):
    """Spaces and lowercase in recovery code should be accepted."""
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")

    code = generate_recovery_code()  # e.g. PUSH-ABCD-EFGH-IJKL-MNOP
    token = encrypt_data_v3("data", "pw", code)

    messy = code.lower().replace("-", " ")
    plaintext, _ = decrypt_data_v3(token, recovery_code=messy)
    assert plaintext == "data"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_vault_crypto.py -k "v3 or recovery" -v
```

Expected: ImportError or AttributeError on `generate_recovery_code` etc.

- [ ] **Step 3: Implement V3 crypto in `pushkey_crypto.py`**

Add after the existing `_V2T_MAGIC` line (line ~38):

```python
_V3_MAGIC = b'PK3\x00'
_V3_HEADER_SIZE = 200  # 4+32+32+12+48+12+48+12 = 200


def generate_recovery_code() -> str:
    """Returns PUSH-XXXX-XXXX-XXXX-XXXX (100 bits entropy, base32)."""
    import base64 as _b64
    raw = secrets.token_bytes(13)
    b32 = _b64.b32encode(raw).decode().rstrip("=")[:20].upper()
    return f"PUSH-{b32[0:4]}-{b32[4:8]}-{b32[8:12]}-{b32[12:16]}"


def _normalize_recovery_code(code: str) -> str:
    return code.upper().replace("-", "").replace(" ", "")


def encrypt_data_v3(data: str, password: str, recovery_code: str) -> bytes:
    salt = get_or_create_salt()
    rec_salt = secrets.token_bytes(32)
    vault_key = secrets.token_bytes(32)

    pw_key = derive_key(password, salt)
    pw_nonce = secrets.token_bytes(12)
    pw_ct = AESGCM(pw_key).encrypt(pw_nonce, vault_key, None)

    norm = _normalize_recovery_code(recovery_code)
    rec_key = derive_key(norm, rec_salt)
    rec_nonce = secrets.token_bytes(12)
    rec_ct = AESGCM(rec_key).encrypt(rec_nonce, vault_key, None)

    body_nonce = secrets.token_bytes(12)
    body_ct = AESGCM(vault_key).encrypt(body_nonce, data.encode(), None)

    return (
        _V3_MAGIC
        + salt
        + rec_salt
        + pw_nonce + pw_ct
        + rec_nonce + rec_ct
        + body_nonce + body_ct
    )


def decrypt_data_v3(
    token: bytes,
    *,
    password: str = None,
    recovery_code: str = None,
) -> tuple[str, bytes]:
    """Returns (plaintext, vault_key). Pass exactly one of password or recovery_code."""
    if not token.startswith(_V3_MAGIC):
        raise ValueError("not_v3")

    payload = token[len(_V3_MAGIC):]
    salt       = payload[0:32]
    rec_salt   = payload[32:64]
    pw_nonce   = payload[64:76]
    pw_ct      = payload[76:124]
    rec_nonce  = payload[124:136]
    rec_ct     = payload[136:184]
    body_nonce = payload[184:196]
    body_ct    = payload[196:]

    if password is not None:
        pw_key = derive_key(password, salt)
        try:
            vault_key = AESGCM(pw_key).decrypt(pw_nonce, pw_ct, None)
        except Exception:
            raise ValueError("wrong_password")
    elif recovery_code is not None:
        norm = _normalize_recovery_code(recovery_code)
        rec_key = derive_key(norm, rec_salt)
        try:
            vault_key = AESGCM(rec_key).decrypt(rec_nonce, rec_ct, None)
        except Exception:
            raise ValueError("wrong_recovery_code")
    else:
        raise ValueError("must pass password or recovery_code")

    try:
        plaintext = AESGCM(vault_key).decrypt(body_nonce, body_ct, None).decode()
    except Exception:
        raise ValueError("body_corrupt")

    return plaintext, vault_key


def rekey_vault(token: bytes, recovery_code: str, new_password: str) -> bytes:
    """Reset master password using recovery code. Returns new V3 token."""
    plaintext, vault_key = decrypt_data_v3(token, recovery_code=recovery_code)

    payload = token[len(_V3_MAGIC):]
    salt      = payload[0:32]
    rec_salt  = payload[32:64]
    rec_nonce = payload[124:136]
    rec_ct    = payload[136:184]

    pw_key = derive_key(new_password, salt)
    pw_nonce = secrets.token_bytes(12)
    pw_ct = AESGCM(pw_key).encrypt(pw_nonce, vault_key, None)

    body_nonce = secrets.token_bytes(12)
    body_ct = AESGCM(vault_key).encrypt(body_nonce, plaintext.encode(), None)

    return (
        _V3_MAGIC
        + salt
        + rec_salt
        + pw_nonce + pw_ct
        + rec_nonce + rec_ct
        + body_nonce + body_ct
    )


def add_recovery_key(token: bytes, password: str, recovery_code: str) -> bytes:
    """Migrate V2 vault to V3 by adding a recovery slot."""
    if token.startswith(_V3_MAGIC):
        plaintext, _ = decrypt_data_v3(token, password=password)
    else:
        plaintext = decrypt_data(token, password)
    return encrypt_data_v3(plaintext, password, recovery_code)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_vault_crypto.py -k "v3 or recovery" -v
```

Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pushkey_crypto.py tests/test_vault_crypto.py
git commit -m "feat: add V3 vault format with recovery key support"
```

---

## Task 2: Update `pushkey_vault.py` — `load_vault` returns tuple, `save_vault` accepts `vault_key`

**Files:**
- Modify: `pushkey_vault.py`
- Test: `tests/test_vault_crypto.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_vault_crypto.py`:

```python
from pushkey_vault import load_vault, save_vault

def test_load_vault_v2_returns_none_key(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")

    save_vault({"MY_KEY": {"value": "abc"}}, "pw")
    vault, vault_key = load_vault("pw")
    assert vault["MY_KEY"]["value"] == "abc"
    assert vault_key is None  # V2 vault → no key

def test_load_vault_v3_returns_vault_key(tmp_path, monkeypatch):
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")

    code = generate_recovery_code()
    save_vault({"MY_KEY": {"value": "abc"}}, "pw", recovery_code=code)
    vault, vault_key = load_vault("pw")
    assert vault["MY_KEY"]["value"] == "abc"
    assert len(vault_key) == 32

def test_save_vault_v3_preserves_vault_key(tmp_path, monkeypatch):
    """Re-saving a V3 vault must use the same vault_key so recovery code still works."""
    import pushkey_shared as _s
    monkeypatch.setattr(_s, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(_s, "SALT_FILE", tmp_path / ".salt")
    monkeypatch.setattr(_s, "VAULT_FILE", tmp_path / "vault.enc")

    code = generate_recovery_code()
    save_vault({"A": {"value": "1"}}, "pw", recovery_code=code)

    vault, vault_key = load_vault("pw")
    vault["B"] = {"value": "2"}
    save_vault(vault, "pw", vault_key=vault_key)

    # Recovery code must still unlock the updated vault
    raw = (_s.VAULT_FILE).read_bytes()
    plaintext, _ = decrypt_data_v3(raw, recovery_code=code)
    import json
    data = json.loads(plaintext)
    assert data["keys"]["B"]["value"] == "2"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_vault_crypto.py -k "load_vault or save_vault" -v
```

Expected: TypeError (load_vault returns dict not tuple).

- [ ] **Step 3: Update `pushkey_vault.py`**

Replace the entire `load_vault` and `save_vault` functions:

```python
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
    log_event,
)


def load_vault(password) -> tuple[dict, bytes | None]:
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
                # Migrate legacy Fernet → V2 (not V3 — user opts in separately)
                pass
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
        # Re-encrypt V3 body with existing vault_key, preserving recovery slot
        existing = _s.VAULT_FILE.read_bytes() if _s.VAULT_FILE.exists() else None
        if existing and existing.startswith(_V3_MAGIC):
            import secrets as _sec
            from pushkey_crypto import AESGCM as _AESGCM
            # Rebuild V3 token keeping same salt, rec_salt, rec slot, but new body + pw slot
            p = existing[4:]
            salt = p[0:32]
            rec_salt = p[32:64]
            rec_nonce = p[124:136]
            rec_ct = p[136:184]

            from pushkey_crypto import derive_key as _dk
            pw_key = _dk(password, salt)
            pw_nonce = _sec.token_bytes(12)
            pw_ct = _AESGCM(pw_key).encrypt(pw_nonce, vault_key, None)

            body_nonce = _sec.token_bytes(12)
            body_ct = _AESGCM(vault_key).encrypt(body_nonce, json_str.encode(), None)

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
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_vault_crypto.py -k "load_vault or save_vault" -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite to check nothing is broken**

```
pytest tests/ -v
```

Expected: all existing tests still PASS (they use `load_vault` return value as a dict — they'll need updating).

- [ ] **Step 6: Fix callers that unpack load_vault in tests**

In `tests/test_vault_crypto.py`, find any calls like `vault = load_vault(pw)` used as a dict and update to `vault, _ = load_vault(pw)`.

Search:
```
grep -n "load_vault" tests/test_vault_crypto.py
```

Update each `vault = load_vault(pw)` → `vault, _ = load_vault(pw)`.

- [ ] **Step 7: Fix callers in `pushkey.py`**

Search for `load_vault` calls:
```
grep -n "load_vault" pushkey.py
```

Each call like `vault = load_vault(pw)` → `vault, vault_key = load_vault(pw)`.

The three call sites are:
1. `pushkey.py:1726` inside `LoginFrame.unlock` — `vault = load_vault(pw)` → `vault, _vault_key = load_vault(pw)` (vault_key stored on a temp var, passed to `on_login`)
2. `pushkey.py:1780` inside `_show_mfa_prompt` closure — same pattern

Then update `on_login` signature and `AppFrame.__init__` to accept and store `vault_key`:

In `LoginFrame.unlock` (around line 1722):
```python
# NEW vault (is_new branch):
ensure_vault_dir()
# Don't save yet — RecoverySetupDialog handles first save (Task 3)
# Temporarily pass vault_key=None; RecoverySetupDialog will call save_vault with recovery_code
self._pending_pw = pw
self._show_recovery_setup(pw)   # NEW — see Task 3
return

# Existing vault branch (line ~1726):
vault, vault_key = load_vault(pw)
if vault is None:
    raise ValueError("wrong_password")
# ... existing MFA check ...
self.on_login(pw, vault, vault_key)
```

In `AppFrame.__init__` (line ~1881), update signature and store:
```python
def __init__(self, master, password, vault, vault_key=None):
    ...
    self.password = password
    self.vault = vault
    self.vault_key = vault_key
```

Update every `save_vault(self.vault, self.password)` call in `AppFrame` to:
```python
save_vault(self.vault, self.password, vault_key=self.vault_key)
```

Search to find all call sites:
```
grep -n "save_vault" pushkey.py
```

- [ ] **Step 8: Run full test suite**

```
pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add pushkey_vault.py pushkey.py tests/test_vault_crypto.py
git commit -m "refactor: load_vault returns (vault, vault_key) tuple; save_vault accepts vault_key"
```

---

## Task 3: `RecoverySetupDialog` + new vault wizard hook in `pushkey.py`

**Files:**
- Modify: `pushkey.py` (LoginFrame.unlock, new `RecoverySetupDialog` class)

This task has no automated tests (UI dialog) — manual verification steps at end.

- [ ] **Step 1: Add `RecoverySetupDialog` class to `pushkey.py`**

Add this class near `LoginFrame` (around line 1430, before `class AppFrame`):

```python
class RecoverySetupDialog(ctk.CTkToplevel):
    """Modal shown during new vault creation to display and confirm the recovery code."""

    def __init__(self, master, password, on_confirmed):
        super().__init__(master)
        self.title("Set Up Recovery Key")
        self.geometry("500x380")
        self.configure(fg_color=C["bg2"])
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        self._password = password
        self._on_confirmed = on_confirmed
        self._code = generate_recovery_code()
        self._confirmed = tk.BooleanVar(value=False)

        ctk.CTkFrame(self, fg_color=C["accent"], height=3).pack(fill="x")

        ctk.CTkLabel(self, text="Save Your Recovery Key",
                     font=(_UI_FONT, 17, "bold"),
                     text_color=C["text"]).pack(pady=(20, 4), padx=24, anchor="w")
        ctk.CTkLabel(
            self,
            text=(
                "If you ever forget your master password, this recovery key\n"
                "lets you set a new one without losing your vault data.\n"
                "Write it down and keep it somewhere safe."
            ),
            font=FONT_SM, text_color=C["text2"],
            anchor="w", justify="left",
        ).pack(padx=24, anchor="w")

        # Code display box
        code_box = ctk.CTkFrame(self, fg_color=C["bg3"], corner_radius=8,
                                border_width=1, border_color=C["accent"])
        code_box.pack(padx=24, pady=(16, 0), fill="x")
        inner = ctk.CTkFrame(code_box, fg_color="transparent")
        inner.pack(padx=12, pady=12, fill="x")
        code_lbl = ctk.CTkLabel(inner, text=self._code,
                                font=("Consolas", 16, "bold"),
                                text_color=C["accent"])
        code_lbl.pack(side="left", expand=True)

        def _copy():
            self.clipboard_clear()
            self.clipboard_append(self._code)
            copy_btn.configure(text="Copied!")
            self.after(1500, lambda: copy_btn.configure(text="Copy"))

        copy_btn = make_btn(inner, "Copy", _copy, width=70, height=28)
        copy_btn.pack(side="right")

        # Confirmation checkbox
        chk_row = ctk.CTkFrame(self, fg_color="transparent")
        chk_row.pack(padx=24, pady=(16, 0), anchor="w")
        ctk.CTkCheckBox(
            chk_row,
            text="I've written this down somewhere safe",
            variable=self._confirmed,
            command=self._toggle_confirm,
            font=FONT_SM, text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent2"],
        ).pack(side="left")

        self._confirm_btn = make_btn(
            self, "Create Vault", self._submit,
            fg_color=C["accent"], text_color="#FFFFFF",
            width=160, height=38,
        )
        self._confirm_btn.pack(pady=(20, 0))
        self._confirm_btn.configure(state="disabled")

        ctk.CTkFrame(self, fg_color="transparent", height=16).pack()

    def _toggle_confirm(self):
        if self._confirmed.get():
            self._confirm_btn.configure(state="normal")
        else:
            self._confirm_btn.configure(state="disabled")

    def _submit(self):
        ensure_vault_dir()
        save_vault({}, self._password, recovery_code=self._code)
        _, vault_key = load_vault(self._password)
        self.destroy()
        self._on_confirmed(self._password, {}, vault_key)
```

- [ ] **Step 2: Update `LoginFrame.unlock` for new vault path**

In `LoginFrame.unlock` (around line 1713), replace:

```python
            ensure_vault_dir()
            save_vault({}, pw)
            self.on_login(pw, {})
```

with:

```python
            RecoverySetupDialog(self, pw, self.on_login)
```

- [ ] **Step 3: Update `LoginFrame.unlock` for existing vault path**

Around line 1726, update `load_vault` call and `on_login` call:

```python
                vault, vault_key = load_vault(pw)
                if vault is None:
                    raise ValueError("wrong_password")
                self._failed_attempts = 0
                self._locked_until = None
                import threading
                threading.Thread(target=maybe_heartbeat, daemon=True).start()
                if mfa_is_enabled():
                    self._show_mfa_prompt(pw, vault, vault_key)
                else:
                    self.on_login(pw, vault, vault_key)
```

- [ ] **Step 4: Update `_show_mfa_prompt` to pass vault_key through**

Find the method signature (line ~1751) and update:

```python
    def _show_mfa_prompt(self, pw, vault, vault_key=None):
```

Find the `self.on_login(pw, vault)` call inside this method (~line 1780) and update:

```python
                self.on_login(pw, vault, vault_key)
```

- [ ] **Step 5: Update `AppFrame.__init__` signature**

Find line ~1878 (`class AppFrame`). Update `__init__`:

```python
    def __init__(self, master, password, vault, vault_key=None):
        ...
        self.password = password
        self.vault = vault
        self.vault_key = vault_key
```

- [ ] **Step 6: Update all `save_vault` calls inside AppFrame**

Run:
```
grep -n "save_vault(self.vault" pushkey.py
```

Replace every occurrence of `save_vault(self.vault, self.password)` with:
```python
save_vault(self.vault, self.password, vault_key=self.vault_key)
```

- [ ] **Step 7: Update `PushkeyApp` callback that wires LoginFrame → AppFrame**

Search for where `on_login` is defined in `PushkeyApp` (grep for `def _on_login` or `on_login=`):

```
grep -n "def _on_login\|lambda pw.*vault\|AppFrame(" pushkey.py
```

Update the callback to accept `vault_key`:

```python
def _on_login(self, password, vault, vault_key=None):
    self._login_frame.destroy()
    self._app_frame = AppFrame(self, password, vault, vault_key)
    self._app_frame.pack(fill="both", expand=True)
```

- [ ] **Step 8: Manual smoke test**

```
python pushkey.py
```

1. Delete `~/.pushkey/vault.enc` if it exists
2. Launch → create vault with a password
3. `RecoverySetupDialog` should appear with `PUSH-XXXX-XXXX-XXXX-XXXX` code
4. Check the checkbox → "Create Vault" button enables
5. Click → app opens normally

- [ ] **Step 9: Commit**

```bash
git add pushkey.py
git commit -m "feat: show RecoverySetupDialog on new vault creation"
```

---

## Task 4: `ForgotPasswordDialog` — replace `_show_restore_hint`

**Files:**
- Modify: `pushkey.py` (LoginFrame._show_restore_hint replacement)

- [ ] **Step 1: Replace `_show_restore_hint` with `_show_forgot_password`**

Find `_show_restore_hint` method (line ~1608). Replace the entire method with:

```python
    def _show_forgot_password(self):
        """Forgot password dialog. Uses recovery key for V3 vaults; shows restore hint for V2."""
        win = ctk.CTkToplevel(self)
        win.title("Forgot Password")
        win.geometry("460x340")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        ctk.CTkFrame(win, fg_color=C["accent"], height=3).pack(fill="x")

        # Detect vault format
        is_v3 = False
        if VAULT_FILE.exists():
            raw = VAULT_FILE.read_bytes()
            is_v3 = raw.startswith(_V3_MAGIC)

        ctk.CTkLabel(win, text="Forgot Password",
                     font=FONT_H2, text_color=C["text"]
                     ).pack(pady=(20, 4), padx=20, anchor="w")

        if not is_v3:
            ctk.CTkLabel(
                win,
                text=(
                    "No recovery key is set up for this vault.\n\n"
                    "Pushkey cannot recover a forgotten master password.\n"
                    "If you have an exported backup file, copy it to:\n"
                    f"  {VAULT_FILE.parent}\n"
                    "as 'vault.enc', then unlock with the password you\n"
                    "used when you created that backup."
                ),
                font=FONT_SM, text_color=C["text2"],
                anchor="w", justify="left",
            ).pack(padx=20, pady=(0, 16), anchor="w")
            make_btn(win, "Got it", win.destroy,
                     fg_color=C["accent"], text_color="#FFFFFF",
                     width=120, height=34).pack(pady=(0, 16))
            return

        # V3 vault — show recovery flow
        ctk.CTkLabel(
            win,
            text="Enter your recovery key to set a new master password.",
            font=FONT_SM, text_color=C["text2"],
        ).pack(padx=20, anchor="w")

        form = ctk.CTkFrame(win, fg_color="transparent")
        form.pack(padx=20, pady=(12, 0), fill="x")

        ctk.CTkLabel(form, text="RECOVERY KEY", font=(_UI_FONT, 9, "bold"),
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 4))
        rec_entry = ctk.CTkEntry(
            form, font=FONT_MONO,
            fg_color=C["bg3"], text_color=C["text"],
            placeholder_text="PUSH-XXXX-XXXX-XXXX-XXXX",
            placeholder_text_color=C["text3"],
            border_color=C["border2"], border_width=1,
            corner_radius=10, height=40,
        )
        rec_entry.pack(fill="x")

        ctk.CTkFrame(form, fg_color="transparent", height=8).pack()
        ctk.CTkLabel(form, text="NEW PASSWORD", font=(_UI_FONT, 9, "bold"),
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 4))
        pw_entry = ctk.CTkEntry(
            form, show="●", font=FONT_MONO,
            fg_color=C["bg3"], text_color=C["text"],
            placeholder_text="New master password",
            placeholder_text_color=C["text3"],
            border_color=C["border2"], border_width=1,
            corner_radius=10, height=40,
        )
        pw_entry.pack(fill="x")

        ctk.CTkFrame(form, fg_color="transparent", height=4).pack()
        ctk.CTkLabel(form, text="CONFIRM PASSWORD", font=(_UI_FONT, 9, "bold"),
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 4))
        pw2_entry = ctk.CTkEntry(
            form, show="●", font=FONT_MONO,
            fg_color=C["bg3"], text_color=C["text"],
            placeholder_text="Re-enter new password",
            placeholder_text_color=C["text3"],
            border_color=C["border2"], border_width=1,
            corner_radius=10, height=40,
        )
        pw2_entry.pack(fill="x")

        err_lbl = ctk.CTkLabel(form, text="", font=FONT_XS, text_color=C["red"])
        err_lbl.pack(pady=(6, 0))

        def _submit():
            rec_code = rec_entry.get().strip()
            new_pw = pw_entry.get().strip()
            new_pw2 = pw2_entry.get().strip()
            if not rec_code:
                err_lbl.configure(text="Enter your recovery key")
                return
            if not new_pw:
                err_lbl.configure(text="Enter a new password")
                return
            if new_pw != new_pw2:
                err_lbl.configure(text="Passwords don't match")
                return
            try:
                raw = VAULT_FILE.read_bytes()
                new_token = rekey_vault(raw, rec_code, new_pw)
                tmp = VAULT_FILE.with_suffix('.tmp')
                tmp.write_bytes(new_token)
                os.replace(str(tmp), str(VAULT_FILE))
                log_event("master password reset via recovery key")
                win.destroy()
                # Show success and pre-fill password field
                self.err.configure(text="Password reset — unlock with your new password",
                                   text_color=C["green"])
                self.pw.delete(0, "end")
            except ValueError as e:
                if "wrong_recovery_code" in str(e):
                    err_lbl.configure(text="Recovery key incorrect — check your written copy")
                else:
                    err_lbl.configure(text=f"Error: {e}")

        make_btn(form, "Reset Password", _submit,
                 fg_color=C["accent"], text_color="#FFFFFF",
                 height=38).pack(fill="x", pady=(12, 0))
        ctk.CTkFrame(win, fg_color="transparent", height=12).pack()
```

- [ ] **Step 2: Update the "Forgot password?" link binding**

Find (line ~1566):
```python
            link.bind("<Button-1>", lambda e: self._show_restore_hint())
```

Replace with:
```python
            link.bind("<Button-1>", lambda e: self._show_forgot_password())
```

- [ ] **Step 3: Add missing imports at top of the method's module scope**

`rekey_vault` and `_V3_MAGIC` are already imported at the top of `pushkey.py` via:
```python
from pushkey_crypto import (
    ...
    _V3_MAGIC,
    rekey_vault,
    ...
)
```

Find the existing import block (line ~84–89 in pushkey.py) and add `_V3_MAGIC` and `rekey_vault` if not already present:

```python
from pushkey_crypto import (
    AESGCM, Fernet, InvalidToken,
    _try_load_argon2, _V2_MAGIC, _V2T_MAGIC, _V3_MAGIC,
    get_or_create_salt, derive_key,
    generate_recovery_code,
    encrypt_data, decrypt_data, team_encrypt, team_decrypt,
    encrypt_data_v3, decrypt_data_v3, rekey_vault, add_recovery_key,
    log_event,
)
```

- [ ] **Step 4: Manual smoke test**

```
python pushkey.py
```

1. With a V2 vault (no recovery key): click "Forgot password?" → see "no recovery key" message with restore hint. ✓
2. With a V3 vault: click "Forgot password?" → see recovery code entry form. Enter wrong code → inline error. Enter correct code + new password → success message on login screen. Unlock with new password. ✓

- [ ] **Step 5: Commit**

```bash
git add pushkey.py
git commit -m "feat: replace restore-hint dialog with ForgotPasswordDialog (recovery key flow)"
```

---

## Task 5: Recovery Key card in Security tab (`render_scan`)

**Files:**
- Modify: `pushkey.py` (render_scan method, ~line 6438)

- [ ] **Step 1: Add `_recovery_key_card` helper method to AppFrame**

Add this method near `render_scan` (after line ~6438):

```python
    def _render_recovery_key_card(self, parent):
        """Recovery key status card for the Security tab."""
        raw = VAULT_FILE.read_bytes() if VAULT_FILE.exists() else b""
        is_v3 = raw.startswith(_V3_MAGIC)

        status_color = C["green"] if is_v3 else C["amber"]
        status_text  = "Active" if is_v3 else "Not configured"
        status_bg    = C["green_bg"] if is_v3 else C["amber_bg"]

        card = ctk.CTkFrame(parent, fg_color=status_color, corner_radius=8)
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color=C["surface"], corner_radius=7,
                             border_width=0)
        inner.pack(fill="x", padx=(4, 0))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)

        # Icon + label column
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="y")
        ctk.CTkLabel(left, text="", image=icon("shield", 16, status_color),
                     width=20).pack(side="left")
        ctk.CTkLabel(left, text="RECOVERY KEY", font=(_UI_FONT, 10, "bold"),
                     text_color=C["text"]).pack(side="left", padx=(6, 0))

        # Status pill
        pill = ctk.CTkFrame(left, fg_color=status_bg, corner_radius=6,
                            border_width=1, border_color=status_color)
        pill.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(pill, text=status_text, font=(_UI_FONT, 9, "bold"),
                     text_color=status_color).pack(padx=8, pady=2)

        # Action button (right side)
        btn_text = "Regenerate" if is_v3 else "Set Up Recovery Key"

        def _setup_or_regen():
            self._recovery_key_setup_flow(regenerate=is_v3)

        make_btn(row, btn_text, _setup_or_regen,
                 fg_color=C["bg3"], text_color=C["text"],
                 width=160, height=28).pack(side="right")
```

- [ ] **Step 2: Add `_recovery_key_setup_flow` method to AppFrame**

Add this method alongside the card helper:

```python
    def _recovery_key_setup_flow(self, regenerate=False):
        """Re-auth → show new recovery code → save V3 vault."""
        win = ctk.CTkToplevel(self)
        win.title("Recovery Key Setup")
        win.geometry("420x280")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        ctk.CTkFrame(win, fg_color=C["accent"], height=3).pack(fill="x")
        ctk.CTkLabel(win, text="Confirm your password",
                     font=FONT_H2, text_color=C["text"]
                     ).pack(pady=(20, 4), padx=20, anchor="w")
        ctk.CTkLabel(win, text="Re-enter your master password to continue.",
                     font=FONT_SM, text_color=C["text2"]
                     ).pack(padx=20, anchor="w")

        form = ctk.CTkFrame(win, fg_color="transparent")
        form.pack(padx=20, pady=(14, 0), fill="x")
        pw_entry = ctk.CTkEntry(
            form, show="●", font=FONT_MONO,
            fg_color=C["bg3"], text_color=C["text"],
            placeholder_text="Master password",
            placeholder_text_color=C["text3"],
            border_color=C["border2"], border_width=1,
            corner_radius=10, height=40,
        )
        pw_entry.pack(fill="x")
        pw_entry.focus_set()

        err_lbl = ctk.CTkLabel(form, text="", font=FONT_XS, text_color=C["red"])
        err_lbl.pack(pady=(6, 0))

        def _verify():
            entered = pw_entry.get().strip()
            result, _ = load_vault(entered)
            if result is None:
                err_lbl.configure(text="Wrong password")
                pw_entry.delete(0, "end")
                return
            win.destroy()
            self._show_recovery_code_dialog(entered)

        make_btn(form, "Continue", _verify,
                 fg_color=C["accent"], text_color="#FFFFFF",
                 height=38).pack(fill="x", pady=(12, 0))
        pw_entry.bind("<Return>", lambda e: _verify())
        ctk.CTkFrame(win, fg_color="transparent", height=12).pack()

    def _show_recovery_code_dialog(self, password):
        """Display new recovery code and save V3 vault on confirm."""
        code = generate_recovery_code()

        win = ctk.CTkToplevel(self)
        win.title("Your Recovery Key")
        win.geometry("500x340")
        win.configure(fg_color=C["bg2"])
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        ctk.CTkFrame(win, fg_color=C["accent"], height=3).pack(fill="x")
        ctk.CTkLabel(win, text="Save Your Recovery Key",
                     font=(_UI_FONT, 17, "bold"),
                     text_color=C["text"]).pack(pady=(20, 4), padx=24, anchor="w")
        ctk.CTkLabel(
            win,
            text="Write this down. It's the only way to recover your vault if\nyou forget your master password.",
            font=FONT_SM, text_color=C["text2"],
            anchor="w", justify="left",
        ).pack(padx=24, anchor="w")

        code_box = ctk.CTkFrame(win, fg_color=C["bg3"], corner_radius=8,
                                border_width=1, border_color=C["accent"])
        code_box.pack(padx=24, pady=(16, 0), fill="x")
        inner = ctk.CTkFrame(code_box, fg_color="transparent")
        inner.pack(padx=12, pady=12, fill="x")
        ctk.CTkLabel(inner, text=code,
                     font=("Consolas", 16, "bold"),
                     text_color=C["accent"]).pack(side="left", expand=True)

        def _copy():
            win.clipboard_clear()
            win.clipboard_append(code)
            copy_btn.configure(text="Copied!")
            win.after(1500, lambda: copy_btn.configure(text="Copy"))

        copy_btn = make_btn(inner, "Copy", _copy, width=70, height=28)
        copy_btn.pack(side="right")

        confirmed = tk.BooleanVar(value=False)
        chk_row = ctk.CTkFrame(win, fg_color="transparent")
        chk_row.pack(padx=24, pady=(16, 0), anchor="w")

        save_btn = make_btn(win, "Save & Activate", lambda: None,
                            fg_color=C["accent"], text_color="#FFFFFF",
                            width=160, height=38)
        save_btn.pack(pady=(16, 0))
        save_btn.configure(state="disabled")

        def _toggle():
            save_btn.configure(state="normal" if confirmed.get() else "disabled")

        ctk.CTkCheckBox(
            chk_row,
            text="I've written this down somewhere safe",
            variable=confirmed, command=_toggle,
            font=FONT_SM, text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent2"],
        ).pack(side="left")

        def _save():
            raw = VAULT_FILE.read_bytes() if VAULT_FILE.exists() else b""
            new_token = add_recovery_key(raw, password, code)
            tmp = VAULT_FILE.with_suffix('.tmp')
            tmp.write_bytes(new_token)
            os.replace(str(tmp), str(VAULT_FILE))
            _, self.vault_key = load_vault(password)
            log_event("recovery key configured")
            win.destroy()
            self.render_scan()  # refresh security tab to show "Active"

        save_btn.configure(command=_save)
        ctk.CTkFrame(win, fg_color="transparent", height=12).pack()
```

- [ ] **Step 3: Wire recovery card into `render_scan`**

In `render_scan` (line ~6458), after the enterprise feature strip block and before the pre-scan state check, add the card:

Find:
```python
        if not self._scan_ts:
```

Insert before it:
```python
        # ── Recovery Key card ─────────────────────────────────────────────
        self._render_recovery_key_card(pad)
```

- [ ] **Step 4: Manual smoke test**

```
python pushkey.py
```

1. Log in with a V2 vault
2. Navigate to Security tab
3. See "RECOVERY KEY — Not configured" card with amber status
4. Click "Set Up Recovery Key" → password prompt → recovery code display → checkbox → "Save & Activate"
5. Card refreshes to show green "Active" status
6. Log out, click "Forgot password?" → now shows recovery key entry form

- [ ] **Step 5: Commit**

```bash
git add pushkey.py
git commit -m "feat: add recovery key card to Security tab with setup/regenerate flow"
```

---

## Task 6: Final test pass and cleanup

**Files:**
- `tests/test_vault_crypto.py`

- [ ] **Step 1: Run full test suite**

```
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run the app end-to-end with a fresh vault**

```powershell
Remove-Item "$env:USERPROFILE\.pushkey\vault.enc" -Force -ErrorAction SilentlyContinue
python pushkey.py
```

Walk through:
1. Create vault → RecoverySetupDialog appears → write down code → confirm → app opens
2. Add a key ("TEST_KEY" = "hello")
3. Close app
4. Reopen → "Forgot password?" → enter recovery code → set new password → unlock → TEST_KEY still present ✓
5. Security tab → recovery key shows "Active" → Regenerate → new code issued ✓

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: recovery key feature complete — V3 vault, setup wizard, forgot-password flow"
```
