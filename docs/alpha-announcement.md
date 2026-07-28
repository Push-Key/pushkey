# 🔑 Pushkey v0.1.1-alpha is here — come break it

**Pushkey is a local-first, encrypted vault for your API keys.** It stores, rotates, and injects your secrets straight into your project `.env` files, all **AES-256-GCM encrypted** with an Argon2id-derived key — no account, no network access, nothing leaves your machine.

We're opening the alpha and we genuinely want you to kick the tires.

---

## What's actually in this alpha

This build is the **CLI + the local web app**. That's it, and that's the part we want tested hard.

> ⚠️ **Cloud sync is experimental and NOT deployed.** Anything you see about backup/sync/multi-device in the UI or docs is roadmap, not reality yet — the backend isn't live, so those paths will not work. Treat this as a purely local tool for now. Everything below runs offline.

---

## Install

**1. Download the binary for your OS** from the release page:
👉 https://github.com/Push-Key/pushkey/releases/tag/v0.1.1-alpha

Grab the matching asset:
- Windows → `pushkey-windows-x64.exe`
- macOS → `pushkey-macos-x64`
- Linux → `pushkey-linux-x64`

**2. Verify the SHA-256 checksum** (do this before you run anything). Compare the output against the value in `SHA256SUMS.txt` on the release page — they must match exactly.

**Windows (PowerShell):**
```powershell
Get-FileHash .\pushkey-windows-x64.exe -Algorithm SHA256
```

**macOS:**
```bash
shasum -a 256 ./pushkey-macos-x64
```

**Linux:**
```bash
sha256sum ./pushkey-linux-x64
```

Or verify the whole set at once (macOS/Linux, run from the download folder):
```bash
sha256sum -c SHA256SUMS.txt
```

If the hash doesn't match, **stop** — don't run it, and ping us.

---

## ⚠️ The binaries are UNSIGNED — your OS will warn you

We haven't set up code signing yet, so the first launch will trip your OS's gatekeeping. That warning is expected. Once you've verified the checksum above, proceed:

- **Windows** — SmartScreen shows "Windows protected your PC." Click **More info → Run anyway**.
- **macOS** — "cannot be opened because the developer cannot be verified." Right-click the binary → **Open** → **Open**, or run `xattr -d com.apple.quarantine ./pushkey-macos-x64`. Then `chmod +x ./pushkey-macos-x64`.
- **Linux** — just make it executable: `chmod +x ./pushkey-linux-x64`.

Only do this **after** the checksum matches. That's what makes it safe.

*(Prefer source? `pip install` / `npm i -g @pushkey/cli` also work — but the signed-binary flow above is what we're asking alpha testers to exercise.)*

---

## 60-second smoke test

```bash
pushkey init                          # set master password, SAVE the PUSH-XXXX recovery code
pushkey add OPENAI_API_KEY sk-abc123  # store a key
cd ~/my-project
pushkey inject                        # writes .env, auto-adds it to .gitignore
pushkey rotate OPENAI_API_KEY sk-new  # rotate it, check the history
pushkey status                        # vault health summary
```

---

## 📋 Read this first

Known issues, deferred items, and exactly what's out of scope for alpha:
👉 **[docs/alpha-known-issues.md](https://github.com/Push-Key/pushkey/blob/main/docs/alpha-known-issues.md)**

Short version: most deferred items live in the cloud/multi-writer paths a single-machine tester never touches. There are two local `.env` edge cases worth knowing — plaintext `.env.pushkey_backup_*` snapshots aren't auto-pruned yet, and a `.env` with invalid (non-UTF-8) bytes can error on inject.

---

## 🙏 What feedback actually helps

Please don't polish-hunt — tell us about the load-bearing stuff:

1. **Onboarding** — did you get from download → verified → `init` → first key without getting stuck? Where did you stall?
2. **Crashes & errors** — anything that throws, hangs, or dies. Paste the command, the error, your OS.
3. **The core flow** — does the vault / rotation / `.env` injection loop actually work for you? Did `inject` write the right keys and guard `.gitignore`? Did `rotate` keep history?

Drop it in this channel or open an issue on the repo. Screenshots and exact repro steps are gold.

Thanks for testing something this early. This is the part where your report changes the product. 🔐

*Build: `v0.1.1-alpha` · commit `aebb37c`*