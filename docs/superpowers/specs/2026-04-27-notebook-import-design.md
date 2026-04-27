# Notebook Import Feature Design
**Date:** 2026-04-27  
**Feature:** Import API keys, projects, and assignments from notebook/text files with dual UI support

---

## Overview

Add ability to upload notebook/text files (Jupyter, plain text, JSON, YAML, CSV) and automatically populate Pushkey vault with API keys, project folders, and key-to-project assignments. Includes interactive review wizard and optional LLM-assisted parsing for improved accuracy.

Accessible via both GUI (tkinter) and TUI (terminal) interfaces. Changes in one interface automatically sync to the other through shared vault.

---

## Architecture

### Layered Design

```
┌─────────────────────────────────────────────────┐
│         SHARED CORE (Business Logic)            │
├─────────────────────────────────────────────────┤
│ • Vault management (encrypt/decrypt)            │
│ • Parser factory (all formats)                  │
│ • Validation engine                             │
│ • LLM enhancement (optional)                    │
│ • Project/key operations                        │
└─────────────────────────────────────────────────┘
              ↓              ↓
    ┌─────────────────┐  ┌──────────────────┐
    │   GUI Layer     │  │   TUI Layer      │
    │   (tkinter)     │  │   (rich/textual) │
    ├─────────────────┤  ├──────────────────┤
    │ • Dashboard     │  │ • Dashboard      │
    │ • All Keys      │  │ • All Keys       │
    │ • Projects      │  │ • Projects       │
    │ • Import        │  │ • Import         │
    └─────────────────┘  └──────────────────┘
              ↓              ↓
    ┌─────────────────────────────────────┐
    │  Shared Vault (encrypted on disk)   │
    └─────────────────────────────────────┘
```

**Key principle:** Both UIs read/write to same vault → changes auto-sync. No synchronization logic needed.

### Entry Points

```bash
python pushkey.py              # GUI (default)
python pushkey.py --tui        # Full TUI app
python pushkey.py --import-gui # GUI import wizard only
python pushkey.py --import-tui # TUI import wizard only
```

---

## Core Components

### 1. Parser Factory (Shared)

**Responsibility:** Convert file formats to standardized `ParseResult`.

**Parsers:**
- `NotebookParser` — Extract from `.ipynb` (code cells + markdown)
- `TextParser` — Extract from `.txt`/`.md` with markers (`@KEY:`, `@PROJECT:`, `@USES:`)
- `JSONParser` — Parse structured JSON
- `CSVParser` — Parse CSV table format
- `YAMLParser` — Parse YAML config

**Interface:**
```python
class Parser:
    def parse(self, filepath: str) -> ParseResult:
        """Return (keys, projects, assignments) or raise ParseError"""

class ParseResult:
    keys: List[KeyInfo]           # (name, value)
    projects: List[ProjectInfo]   # (path)
    assignments: Dict[str, List[str]]  # {project_path: [key_names]}
```

**Format Detection:**
- By file extension
- By file header (magic bytes for .ipynb, first line for JSON, etc.)

### 2. Validation Engine (Shared)

**Validators:**
- **Key name:** Must be valid env var (alphanumeric + underscore, starts with letter)
- **Key value:** Must not be empty
- **Project path:** Check if exists on disk (warn if missing, allow override)
- **Assignments:** All referenced keys must exist or be creatable

**Output:** `ValidationResult` with errors, warnings, suggestions

### 3. LLM Enhancement (Phase 2, Optional)

**When enabled:**
1. Parse with Phase 1 parser
2. Send to LLM with prompt: "Validate this extraction, fix errors, suggest missing connections"
3. Merge LLM suggestions with original parse
4. Show diff to user in wizard

**Configuration:**
```json
{
  "llm_parsing": {
    "enabled": false,
    "prefer_local": true,
    "ollama_url": "http://localhost:11434",
    "anthropic_api_key": null
  }
}
```

**Priority:**
1. Try local Ollama (if running)
2. Fallback to user's Anthropic API key (if set)
3. Skip if neither available (Phase 1 parser still works)

### 4. Import Wizard (Both GUI + TUI)

**Flow:**
1. **File picker** — Select file to import
2. **Format detection** — Auto-detect or user confirms
3. **Parsing** — Run parser(s)
4. **Review screen** — Color-coded display of keys, projects, assignments
5. **Conflict resolution** — Address duplicates, missing paths, etc.
6. **Confirmation** — Summary of what will be added/updated
7. **Commit** — Write to vault

### 5. Conflict Resolution Strategy (Smart Hybrid)

| Scenario | Action |
|----------|--------|
| Key exists + same value | Skip silently |
| Key exists + different value | Ask "Overwrite?" |
| Project path doesn't exist | Warn but allow skip/proceed |
| Assignment references missing key | Ask "Create key?" or "Skip assignment?" |
| Duplicate keys in import | Ask which to keep |
| Invalid key name format | Error, skip item |

---

## File Format Specifications

### Text Format (`.txt`, `.md`)

**Markers:**
```
@KEY: KEY_NAME = value
@PROJECT: /path/to/project
@USES: /path/to/project: KEY_1, KEY_2
```

**Example:**
```
## My API Keys Setup

@KEY: OPENAI_API_KEY = sk-proj-abc123def456
@KEY: OANDA_API_KEY = 12345678-abcd-efgh-ijkl
@KEY: STRIPE_API_KEY = sk_live_xyz789

## My Projects

@PROJECT: /home/user/project-alpha
@PROJECT: /home/user/project-beta

## Key Assignments

@USES: /home/user/project-alpha: OPENAI_API_KEY, OANDA_API_KEY
@USES: /home/user/project-beta: OPENAI_API_KEY, STRIPE_API_KEY
```

### JSON Format

```json
{
  "keys": [
    {"name": "OPENAI_API_KEY", "value": "sk-proj-..."},
    {"name": "OANDA_API_KEY", "value": "..."}
  ],
  "projects": [
    "/home/user/project-alpha",
    "/home/user/project-beta"
  ],
  "assignments": {
    "/home/user/project-alpha": ["OPENAI_API_KEY", "OANDA_API_KEY"],
    "/home/user/project-beta": ["OPENAI_API_KEY"]
  }
}
```

### CSV Format

```
key_name,key_value,project_path
OPENAI_API_KEY,sk-...,/home/user/project-alpha
OANDA_API_KEY,12345,...,/home/user/project-beta
STRIPE_API_KEY,sk_live_...,/home/user/project-beta
```

### Jupyter Notebook (`.ipynb`)

**Extraction rules:**
- Code cells: Look for `os.environ["KEY_NAME"] = "value"` or `.env` assignment patterns
- Markdown cells: Extract `@KEY:` markers
- Cell tags: Optional `pushkey-import` tag to mark relevant cells

---

## Color Coding System

### Provider Colors (Semantic)

```
OpenAI          → Blue (#0066FF)
Anthropic       → Purple (#9933FF)
Stripe          → Teal (#00CCCC)
OANDA           → Green (#00CC00)
Alpaca          → Orange (#FF9900)
AWS             → Gold (#FFCC00)
Coinbase        → Navy (#003366)
Supabase        → Forest Green (#00CC66)
Vercel          → Black (#000000)
Other/Unknown   → Gray (#808080)
```

### Status Indicators

```
🟢 New (will be added)        → Green (#00FF00)
🟡 Conflict/Warning           → Yellow (#FFFF00)
🔴 Error/Invalid              → Red (#FF0000)
⚫ Skipped                     → Gray (#808080)
```

### Visual Rendering

**GUI (tkinter):**
- Key cards: Provider color background, status badge (top-right)
- Project rows: Neutral background, status badge
- Assignment rows: Provider color text, status indicator

**TUI (rich/textual):**
- Tables with ANSI color codes
- Status symbols (●◐◑○ or emoji)
- Box drawing for visual groups

---

## Data Flow

### Import Process

```
User selects file
    ↓
Format detection (extension + content)
    ↓
Parse (route to appropriate parser)
    ↓
ParseResult {keys, projects, assignments}
    ↓
[Optional] LLM enhancement
    ↓
Validation (check all rules)
    ↓
ValidationResult {errors, warnings, suggestions}
    ↓
Review Wizard (display + allow edits)
    ↓
User confirms (or revises)
    ↓
Conflict resolution (smart hybrid rules)
    ↓
Commit to vault:
    ├─ Add/update keys (encrypted)
    ├─ Add projects (config)
    └─ Create assignments
    ↓
Success summary
```

### Synchronization (GUI ↔ TUI)

- Both UIs use shared `Vault` class
- Vault reads/writes same encrypted file
- No explicit sync needed; changes visible on next vault read
- Optional: File watcher to reload if external changes detected

---

## Error Handling

### Parser Errors
- Invalid format → Clear message + "Choose different file format"
- Corrupted file → "File appears to be corrupted, cannot parse"
- Empty file → "No data found in file"

### Validation Errors
- Invalid key name → "KEY_NAME is not a valid environment variable name"
- Missing project path → "Path does not exist: /invalid/path (allow skip?)"
- Missing key reference → "Assignment references KEY_XYZ which was not found"

### Vault Errors
- Write failure → "Could not write to vault. Check file permissions."
- Encryption failure → "Encryption error. Master password may be incorrect."

---

## Testing Strategy

### Unit Tests
- Parser correctness (each format)
- Validation rules (key names, paths, assignments)
- Conflict resolution logic
- Color mapping

### Integration Tests
- Full import flow (file → wizard → vault)
- Dual UI sync (update in GUI, read in TUI)
- LLM enhancement (if enabled)

### Manual Tests
- Import each file format
- Trigger each conflict scenario
- Test color rendering in GUI and TUI
- Verify .env files updated correctly

---

## Phase Breakdown

### Phase 1: Core (Required)

- [ ] Parser factory (all 5 formats)
- [ ] Validation engine
- [ ] Import wizard (GUI + TUI)
- [ ] Color coding system
- [ ] Conflict resolution
- [ ] Tests

### Phase 2: Enhancement (Optional)

- [ ] LLM integration (local-first)
- [ ] Advanced validation (LLM-suggested fixes)
- [ ] Diff preview (show what will change)

### Phase 3: Polish (Nice-to-have)

- [ ] Batch import (multiple files)
- [ ] Import history/undo
- [ ] Template library (for users to share formats)

---

## Success Criteria

✅ Can import all 5 file formats  
✅ Wizard shows color-coded keys/projects/assignments  
✅ Smart conflict resolution (not too many prompts)  
✅ Works in both GUI and TUI  
✅ Changes sync between UIs  
✅ .env files auto-updated for linked projects  
✅ Handles edge cases (missing paths, invalid names)  
✅ Unit test coverage > 80%

---

## Out of Scope

- Batch upload (one file at a time)
- Cloud sync (local only)
- UI for editing parsed results (wizard shows, user confirms/skips, not line-by-line edit)
- Integration with cloud services (vault is local-only)

---

## Dependencies

- `cryptography` (existing)
- `rich` (TUI coloring and tables)
- `textual` (optional, full TUI framework upgrade later)
- Python 3.8+
