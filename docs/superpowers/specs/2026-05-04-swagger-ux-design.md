# Swagger-Inspired UX for All Keys Tab

**Date:** 2026-05-04  
**Scope:** `pushkey.py` — All Keys tab only  
**Status:** Approved, ready for implementation

---

## Summary

Redesign the All Keys tab in the Pushkey desktop GUI with Swagger UI interaction patterns: accordion key rows, inline two-pane detail panels, inline rotation sub-panel, and copy flash feedback. Zero new infrastructure — all changes are presentation layer on top of existing vault data and action handlers.

---

## Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Accordion layout | Two-pane card (value+meta left, actions right) | Most readable at a glance |
| Multi-expand | Single-open — opening a row closes the previous | Matches Swagger, reduces visual noise |
| Detail modal | Removed entirely — accordion is the full detail view | Eliminates context-switching |
| Rotation flow | Inline sub-panel within the accordion | No popup windows |
| Copy feedback | Flash button green for 1500ms | Instant confirmation without re-render |
| Platform | Desktop GUI (pushkey.py) — not web | Vault is local-first; web dashboard is out of scope |

---

## State

Two new instance vars on `AppFrame.__init__`:

```python
self._expanded_key: str | None = None   # which key row is open
self._rotate_pending: bool = False       # inline rotation input visible
```

**`_expanded_key` cleared when:**
- Search query changes
- Group-by toggles
- Tab switches away from keys
- User clicks the open row again (toggle)

**`_rotate_pending` cleared when:**
- `_expanded_key` changes
- User cancels rotation
- Rotation completes (result strip takes over)

---

## Components

### 1. Collapsed Row (modified `_render_single_key`)

- Add `▶`/`▼` chevron as leftmost element
  - Closed: `C["text3"]`, Open: `C["accent"]`
- Click handler: `show_key_detail(n)` → `_toggle_expand(n)`
- Everything else unchanged (checkbox, cat dot, name, env pill, health pill, action buttons)

### 2. Expanded Two-Pane Panel (new, rendered in `_render_key_rows`)

Rendered directly below the matched row, inside `self.keys_scroll`.

**Left pane** (`flex: 1`, `border-right: 1px C["border"]`):
- VALUE label + masked value box with show/hide toggle
- 2×2 meta grid: provider, env, created, rotated
- Project tags strip (linked projects)

**Right pane** (`width: 148px`):
- ACTIONS label
- Stacked buttons: Copy Value, Rotate, Inject .env, Revoke

**Panel border:** `C["accent"]` on left/right/bottom; top uses `C["accent"]` at reduced opacity to read as connected to the row above.

**Category accent bar:** 3px left border using `CAT_COLORS[category]` — the Swagger method-color pattern applied to provider categories.

### 3. Inline Rotation Sub-Panel (new)

Appended below the expand panel when Rotate is clicked (`_rotate_pending = True`).

- Amber-tinted background strip (`C["amber_bg"]`)
- Input field pre-focused, placeholder: `"Paste new key value..."`
- Confirm Rotate button + Cancel button
- Hint text: `"Old value backed up to history"`

**On confirm:**
1. Calls existing `_apply_rotation(name, new_value)`
2. `_rotate_pending = False`
3. Re-render — result strip appears in place of sub-panel:
   - Green `✓ Rotated` label
   - New masked value + ⎘ Copy button
   - Auto-dismiss after 8s via `after(8000, _render_key_rows)`

**On cancel:** `_rotate_pending = False`, `_render_key_rows()`

**API auto-rotation exception:** Keys where `provider in {"OpenAI", "Anthropic", "AWS"}` keep the existing Toplevel rotation modal — that flow requires credential input fields too complex for inline treatment.

### 4. Copy Flash Feedback (modified `copy_key`)

```python
def copy_key(self, value, flash_widget=None):
    self.clipboard_clear()
    self.clipboard_append(value)
    job_id = self.after(30000, self.clipboard_clear)
    self._clipboard_jobs.append(job_id)
    if flash_widget:
        flash_widget.configure(text="✓ Copied", text_color=C["green"])
        self.after(1500, lambda: flash_widget.configure(
            text="⎘ Copy Value", text_color=C["text2"]))
```

No full re-render. Direct `configure()` on the button widget.

---

## New Method

```python
def _toggle_expand(self, name: str):
    if self._expanded_key == name:
        self._expanded_key = None
    else:
        self._expanded_key = name
    self._rotate_pending = False
    self._render_key_rows()
```

---

## Files Changed

| File | Change |
|------|--------|
| `pushkey.py` | `_render_single_key()` — chevron + swap click handler |
| `pushkey.py` | `_render_key_rows()` — inject expansion panel after matched row |
| `pushkey.py` | `_toggle_expand()` — new 3-line method |
| `pushkey.py` | `copy_key()` — add `flash_widget` param |
| `pushkey.py` | `AppFrame.__init__` — add `_expanded_key`, `_rotate_pending` |
| `pushkey.py` | Remove `show_key_detail()` modal |

---

## What's NOT Changing

- All crypto, vault, and save logic
- CLI (`pushkey_cli.py`)
- Web dashboard (`web/`)
- All other tabs: Dashboard, Projects, Security, Cloud, Timeline
- API auto-rotation modal (OpenAI/Anthropic/AWS keeps Toplevel)
- Group headers, search, env filter pills, bulk select, group-by toggle
- `_render_key_rows()` wipe-and-rebuild pattern

---

## Success Criteria

- Clicking a key row expands it inline; clicking again collapses it
- Opening row B while row A is open collapses A automatically
- Expanded panel shows value (masked), provider, env, created, rotated, projects
- Rotate button shows inline sub-panel with input + confirm + cancel
- Confirm rotation calls `_apply_rotation`, shows result strip, auto-dismisses after 8s
- Copy button flashes green for 1500ms without triggering a re-render
- API auto-rotation (OpenAI/Anthropic/AWS) still opens the existing modal
- All existing tests pass (107 tests)
