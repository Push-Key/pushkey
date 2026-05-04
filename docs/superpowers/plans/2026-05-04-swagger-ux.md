# Swagger-Inspired UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the All Keys tab in `pushkey.py` with Swagger-inspired UX: accordion rows, inline two-pane detail panels, inline rotation sub-panel, and copy flash feedback.

**Architecture:** Add `_expanded_key` / `_rotate_pending` state to `AppFrame`, extend `_render_key_rows` to inject an expansion panel below the matched row, and modify `_render_single_key` to add a chevron + swap the click handler. All changes are in `pushkey.py` only — no new files, no new dependencies.

**Tech Stack:** Python 3, CustomTkinter (`ctk`), tkinter (`tk`). All existing patterns (wipe-and-rebuild render, `make_btn`, `CAT_COLORS`, `C` color dict) are reused.

**Spec:** `docs/superpowers/specs/2026-05-04-swagger-ux-design.md`

---

## Critical Notes Before Starting

- `show_key_detail()` (line 6059) is called from **Timeline/Lifecycle** (lines 3811–3856) and **Dashboard forecast** (lines 4798–4810) — **do NOT remove it**. Only the 3 bindings inside `_render_single_key` (lines 5042, 5053, 5131) get replaced.
- `_render_key_rows()` wipes and rebuilds everything on each call — this is the existing pattern, do not change it.
- All tests live in `tests/`. Run `pytest` (107 tests) after each task to catch regressions.
- `make_btn(parent, text, command, **kwargs)` is the button factory at line ~2088.
- Color tokens live in the global `C` dict. Key tokens: `C["accent"]`, `C["text3"]`, `C["surface"]`, `C["border"]`, `C["amber_bg"]`, `C["amber"]`, `C["green"]`, `C["green_bg"]`, `C["red_bg"]`, `C["red"]`.
- `CAT_COLORS` dict at line 1256 maps category string → hex color.

---

## File Map

| File | Lines | Change |
|------|-------|--------|
| `pushkey.py` | 2088–2099 | Add `_expanded_key`, `_rotate_pending` to `AppFrame.__init__` |
| `pushkey.py` | after line 5007 | Add `_toggle_expand()` method |
| `pushkey.py` | 5038–5131 | Modify `_render_single_key()` — chevron + click handler swap |
| `pushkey.py` | 4992–4994 | Modify `_render_key_rows()` — inject expansion panel |
| `pushkey.py` | after `_toggle_group` | Add `_render_expand_panel()` method |
| `pushkey.py` | 5771–5775 | Modify `copy_key()` — add `flash_widget` param |
| `pushkey.py` | 4996–4999 | Modify `_toggle_group_by()` — clear expanded state |
| `pushkey.py` | 4923–4926 | Modify `_on_search_change()` — clear expanded state |

---

## Task 1: Add state vars and `_toggle_expand` method

**Files:**
- Modify: `pushkey.py:2088-2099` (`AppFrame.__init__` state block)
- Modify: `pushkey.py:5001-5007` (after `_toggle_group`, before `_render_single_key`)
- Test: `tests/test_ui_helpers.py`

- [ ] **Step 1: Write a failing test for `_toggle_expand`**

Add to `tests/test_ui_helpers.py`:

```python
def test_toggle_expand_opens_key(tmp_path, monkeypatch):
    """_toggle_expand sets _expanded_key and clears _rotate_pending."""
    import types, tkinter as tk
    # Minimal stub — we only need the state logic, not a real window
    class FakeApp:
        _expanded_key = None
        _rotate_pending = False
        _render_called = False
        def _render_key_rows(self):
            self._render_called = True

    app = FakeApp()
    # Bind the real method to the stub
    import pushkey as pk
    app._toggle_expand = types.MethodType(pk.AppFrame._toggle_expand, app)

    app._toggle_expand("OPENAI_API_KEY")
    assert app._expanded_key == "OPENAI_API_KEY"
    assert app._rotate_pending is False
    assert app._render_called is True


def test_toggle_expand_closes_same_key(tmp_path, monkeypatch):
    """Calling _toggle_expand on the already-open key collapses it."""
    import types
    class FakeApp:
        _expanded_key = "OPENAI_API_KEY"
        _rotate_pending = True
        _render_called = False
        def _render_key_rows(self):
            self._render_called = True

    app = FakeApp()
    import pushkey as pk
    app._toggle_expand = types.MethodType(pk.AppFrame._toggle_expand, app)

    app._toggle_expand("OPENAI_API_KEY")
    assert app._expanded_key is None
    assert app._rotate_pending is False


def test_toggle_expand_switches_key(tmp_path, monkeypatch):
    """Opening key B while key A is open replaces A with B."""
    import types
    class FakeApp:
        _expanded_key = "KEY_A"
        _rotate_pending = True
        _render_called = False
        def _render_key_rows(self):
            self._render_called = True

    app = FakeApp()
    import pushkey as pk
    app._toggle_expand = types.MethodType(pk.AppFrame._toggle_expand, app)

    app._toggle_expand("KEY_B")
    assert app._expanded_key == "KEY_B"
    assert app._rotate_pending is False
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_ui_helpers.py::test_toggle_expand_opens_key -v
```

Expected: `AttributeError: type object 'AppFrame' has no attribute '_toggle_expand'`

- [ ] **Step 3: Add state vars to `AppFrame.__init__`**

In `pushkey.py`, find the state block starting at line 2088. After `self._search_debounce_id = None` (line 2099), add:

```python
        self._expanded_key: str | None = None
        self._rotate_pending: bool = False
        self._rotate_result: str | None = None
```

- [ ] **Step 4: Add `_toggle_expand` method**

In `pushkey.py`, after `_toggle_group` (which ends around line 5006), insert:

```python
    def _toggle_expand(self, name: str):
        if self._expanded_key == name:
            self._expanded_key = None
        else:
            self._expanded_key = name
        self._rotate_pending = False
        self._render_key_rows()
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_ui_helpers.py -v
```

Expected: all 3 new tests pass, existing tests unaffected.

- [ ] **Step 6: Commit**

```
git add pushkey.py tests/test_ui_helpers.py
git commit -m "feat: add _expanded_key state and _toggle_expand method"
```

---

## Task 2: Add chevron to collapsed rows and swap click handler

**Files:**
- Modify: `pushkey.py:5038-5131` (`_render_single_key`)

- [ ] **Step 1: Read the current `_render_single_key` implementation**

Read lines 5008–5131 of `pushkey.py` to understand the exact current structure before touching it.

- [ ] **Step 2: Replace the 3 `show_key_detail` bindings with `_toggle_expand`**

Find these 3 lines in `_render_single_key` (around lines 5042, 5053, 5131):

```python
        row.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))
```
```python
        inner.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))
```
```python
        name_lbl.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))
```

Replace each with `_toggle_expand`:

```python
        row.bind("<Button-1>", lambda e, n=name: self._toggle_expand(n))
```
```python
        inner.bind("<Button-1>", lambda e, n=name: self._toggle_expand(n))
```
```python
        name_lbl.bind("<Button-1>", lambda e, n=name: self._toggle_expand(n))
```

- [ ] **Step 3: Add the chevron label**

In `_render_single_key`, find where `inner` is built and packed (around line 5051):

```python
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=4)
        inner.bind("<Button-1>", lambda e, n=name: self._toggle_expand(n))
```

Immediately after the `inner.bind(...)` line, add the chevron as the first child of `inner` (before the checkbox):

```python
        is_expanded = (name == self._expanded_key)
        chevron_color = C["accent"] if is_expanded else C["text3"]
        chevron_text = "▼" if is_expanded else "▶"
        ctk.CTkLabel(
            inner, text=chevron_text, font=(_UI_FONT, 10),
            text_color=chevron_color, width=14,
        ).pack(side="left", padx=(0, 4))
```

- [ ] **Step 4: Style the row border when expanded**

Still in `_render_single_key`, find where `row` is built (around line 5038):

```python
        row = ctk.CTkFrame(self.keys_scroll, fg_color=C["surface"],
                           corner_radius=6, border_width=1,
                           border_color=C["border"], cursor="hand2")
```

Replace with:

```python
        is_expanded = (name == self._expanded_key)
        row = ctk.CTkFrame(
            self.keys_scroll,
            fg_color=C["surface"],
            corner_radius=6 if not is_expanded else 0,
            border_width=1,
            border_color=C["accent"] if is_expanded else C["border"],
            cursor="hand2",
        )
```

And update the hover handlers to keep the accent border when expanded:

```python
        def _hover_in(e, r=row):
            r.configure(fg_color=C["bg3"])
            if not is_expanded:
                r.configure(border_color=C["accent"])
        def _hover_out(e, r=row):
            r.configure(fg_color=C["surface"])
            if not is_expanded:
                r.configure(border_color=C["border"])
```

- [ ] **Step 5: Run the app manually to verify**

```
python pushkey.py
```

Navigate to All Keys tab. Verify rows show `▶` chevron. Clicking a row no longer opens the old detail modal — instead it does nothing visible yet (expansion panel not wired yet, coming in Task 4).

- [ ] **Step 6: Run tests**

```
pytest -x
```

Expected: all 107 tests pass.

- [ ] **Step 7: Commit**

```
git add pushkey.py
git commit -m "feat: add accordion chevron and swap click handler in All Keys rows"
```

---

## Task 3: Build `_render_expand_panel` method

**Files:**
- Modify: `pushkey.py` — add new method after `_toggle_group` block (around line 5007)

This method renders the two-pane expansion panel. It is called by `_render_key_rows` immediately after `_render_single_key` for the currently expanded key.

- [ ] **Step 1: Add `_render_expand_panel` after `_toggle_expand`**

Insert this method in `pushkey.py` after `_toggle_expand`:

```python
    def _render_expand_panel(self, name: str, info: dict):
        """Two-pane expansion panel rendered below the open accordion row."""
        cat        = info.get("category", "General")
        cat_col    = CAT_COLORS.get(cat, C["text3"])
        provider   = info.get("provider", "")
        env        = info.get("env", "all")
        created    = info.get("created", "")[:10] if info.get("created") else "—"
        rotated_ts = info.get("rotated", "")
        val        = info["value"]
        revealed   = name in self.revealed
        projects   = [p.get("name", p) if isinstance(p, dict) else p
                      for p in info.get("projects", [])]

        # Days-since helper for rotated label
        if rotated_ts:
            try:
                from datetime import datetime
                delta = (datetime.now() - datetime.fromisoformat(rotated_ts)).days
                rotated_str = f"{delta}d ago"
                rotated_col = C["red"] if delta > 90 else C["amber"] if delta > 60 else C["text2"]
            except Exception:
                rotated_str = rotated_ts[:10]
                rotated_col = C["text2"]
        else:
            rotated_str = "never"
            rotated_col = C["amber"]

        # ── Outer wrapper — connected to the row above ──
        # 3px left accent bar using category color (Swagger method-color pattern)
        outer = ctk.CTkFrame(
            self.keys_scroll,
            fg_color=cat_col,
            corner_radius=0,
            border_width=0,
        )
        outer.pack(fill="x", padx=4, pady=(0, 6))

        inner_bg = ctk.CTkFrame(
            outer,
            fg_color=C["bg2"],
            corner_radius=0,
            border_width=1,
            border_color=C["accent"],
        )
        inner_bg.pack(fill="x", padx=(3, 0))  # 3px gap = left accent bar

        # ── Body: left pane + divider + right pane ──
        body = ctk.CTkFrame(inner_bg, fg_color="transparent")
        body.pack(fill="x")

        # LEFT PANE
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=(14, 0), pady=10)

        # VALUE label + box
        ctk.CTkLabel(left, text="VALUE", font=(_UI_FONT, 9, "bold"),
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 3))

        val_row = ctk.CTkFrame(left, fg_color=C["bg3"], corner_radius=4,
                               border_width=1, border_color=C["border"])
        val_row.pack(fill="x", pady=(0, 8))

        display_val = val if revealed else "●" * min(len(val), 24)
        val_lbl = ctk.CTkLabel(val_row, text=display_val,
                               font=(_MONO_FONT, 11),
                               text_color=C["accent"] if not revealed else C["text"],
                               anchor="w")
        val_lbl.pack(side="left", padx=8, pady=4, fill="x", expand=True)

        def _toggle_reveal_inline():
            if name in self.revealed:
                self.revealed.discard(name)
            else:
                self.revealed.add(name)
                self.after(10000, lambda: (self.revealed.discard(name),
                                           self._render_key_rows()))
            self._render_key_rows()

        show_btn = make_btn(val_row, "Hide" if revealed else "Show",
                            _toggle_reveal_inline,
                            fg_color="transparent", text_color=C["text3"],
                            width=38, height=22, border=False)
        show_btn.pack(side="right", padx=(0, 4))

        # META GRID (2×2)
        meta = ctk.CTkFrame(left, fg_color="transparent")
        meta.pack(fill="x", pady=(0, 6))
        meta.columnconfigure(0, weight=1)
        meta.columnconfigure(1, weight=1)

        def _meta_cell(parent, row, col, label, value, val_color=None):
            cell = ctk.CTkFrame(parent, fg_color="transparent")
            cell.grid(row=row, column=col, sticky="w", pady=1)
            ctk.CTkLabel(cell, text=label, font=(_UI_FONT, 9, "bold"),
                         text_color=C["text3"]).pack(anchor="w")
            ctk.CTkLabel(cell, text=value, font=(_MONO_FONT, 10),
                         text_color=val_color or C["text2"]).pack(anchor="w")

        _meta_cell(meta, 0, 0, "PROVIDER", provider or "—")
        _meta_cell(meta, 0, 1, "ENV", env.upper())
        _meta_cell(meta, 1, 0, "CREATED", created)
        _meta_cell(meta, 1, 1, "ROTATED", rotated_str, rotated_col)

        # PROJECT TAGS
        if projects:
            tags_row = ctk.CTkFrame(left, fg_color="transparent")
            tags_row.pack(fill="x")
            ctk.CTkLabel(tags_row, text="PROJECTS", font=(_UI_FONT, 9, "bold"),
                         text_color=C["text3"]).pack(anchor="w", pady=(0, 3))
            pills_row = ctk.CTkFrame(tags_row, fg_color="transparent")
            pills_row.pack(fill="x")
            for proj in projects[:6]:
                tag = ctk.CTkFrame(pills_row, fg_color=C["bg3"], corner_radius=10,
                                   border_width=1, border_color=C["border2"])
                tag.pack(side="left", padx=(0, 4), pady=1)
                ctk.CTkLabel(tag, text=str(proj), font=(_UI_FONT, 9),
                             text_color=C["accent"]).pack(padx=6, pady=1)

        # VERTICAL DIVIDER
        ctk.CTkFrame(body, fg_color=C["border"], width=1,
                     corner_radius=0).pack(side="left", fill="y", pady=8)

        # RIGHT PANE — action buttons
        right = ctk.CTkFrame(body, fg_color="transparent", width=150)
        right.pack(side="left", fill="y", padx=12, pady=10)
        right.pack_propagate(False)

        ctk.CTkLabel(right, text="ACTIONS", font=(_UI_FONT, 9, "bold"),
                     text_color=C["text3"]).pack(anchor="w", pady=(0, 6))

        # Copy Value button (with flash feedback)
        copy_btn = make_btn(
            right, "⎘  Copy Value",
            lambda: None,  # patched below after widget exists
            fg_color=C["btn"], text_color=C["accent"],
            width=126, height=28, border=False,
        )
        copy_btn.configure(command=lambda: self.copy_key(val, flash_widget=copy_btn))
        copy_btn.pack(fill="x", pady=(0, 4))

        # Rotate button
        API_ROTATE = {"OpenAI", "Anthropic", "AWS"}
        if provider in API_ROTATE:
            # Complex flow — keep existing modal
            make_btn(right, "↻  Rotate",
                     lambda n=name: self.rotate_key(n),
                     fg_color=C["amber_bg"], text_color=C["amber"],
                     width=126, height=28, border=False).pack(fill="x", pady=(0, 4))
        else:
            # Simple flow — inline sub-panel
            make_btn(right, "↻  Rotate",
                     lambda: self._show_rotate_subpanel(name),
                     fg_color=C["amber_bg"], text_color=C["amber"],
                     width=126, height=28, border=False).pack(fill="x", pady=(0, 4))

        # Inject .env
        make_btn(right, "→  Inject .env",
                 lambda n=name: self._inline_inject(n),
                 fg_color=C["btn"], text_color=C["green"],
                 width=126, height=28, border=False).pack(fill="x", pady=(0, 4))

        # Revoke
        make_btn(right, "✕  Revoke",
                 lambda n=name: self.delete_key(n),
                 fg_color=C["red_bg"], text_color=C["red"],
                 width=126, height=28, border=False).pack(fill="x")

        # ── Inline rotation sub-panel (if pending) ──
        if self._rotate_pending and self._expanded_key == name:
            self._render_rotate_subpanel(inner_bg, name)
```

- [ ] **Step 2: Add `_inline_inject` helper**

After `_render_expand_panel`, add:

```python
    def _inline_inject(self, name: str):
        """Inject .env for one key and show brief status in the panel."""
        injected, errors = self._auto_inject_key(name)
        msg = f"Injected to {injected} project(s)" if injected else "No linked projects"
        if errors:
            msg += f" ({len(errors)} error(s))"
        # Brief status via existing toast/statusbar — just re-render to show result
        self._invalidate_tabs("dashboard", "keys", "timeline")
```

- [ ] **Step 3: Run tests**

```
pytest -x
```

Expected: all tests pass (this method has no test — it's UI-only rendering code).

- [ ] **Step 4: Add method stubs for Task 5 methods (prevents AttributeError before Task 5)**

After `_inline_inject`, add these stubs so clicking Rotate before Task 5 is complete doesn't crash:

```python
    def _show_rotate_subpanel(self, name: str):
        pass  # replaced in Task 5

    def _render_rotate_subpanel(self, parent_frame, name: str):
        pass  # replaced in Task 5

    def _dismiss_rotate_result(self):
        pass  # replaced in Task 5
```

- [ ] **Step 5: Run tests**

```
pytest -x
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```
git add pushkey.py
git commit -m "feat: add _render_expand_panel two-pane card method"
```

---

## Task 4: Wire expansion panel into `_render_key_rows`

**Files:**
- Modify: `pushkey.py:4992-4994` (`_render_key_rows` inner loop)

- [ ] **Step 1: Read the current loop in `_render_key_rows`**

Read lines 4970–4994 of `pushkey.py`. The inner loop looks like:

```python
        if not collapsed:
            for name, info in items:
                self._render_single_key(name, info)
```

- [ ] **Step 2: Inject expansion panel after matched row**

Replace that inner loop with:

```python
        if not collapsed:
            for name, info in items:
                self._render_single_key(name, info)
                if name == self._expanded_key:
                    self._render_expand_panel(name, info)
```

- [ ] **Step 3: Run the app and verify accordion works**

```
python pushkey.py
```

- Open the All Keys tab
- Click any key row → two-pane panel should appear below it
- Click the same row again → panel collapses
- Click a different row → first panel closes, new one opens

- [ ] **Step 4: Run tests**

```
pytest -x
```

Expected: all 107 tests pass.

- [ ] **Step 5: Commit**

```
git add pushkey.py
git commit -m "feat: wire accordion expansion panel into _render_key_rows"
```

---

## Task 5: Inline rotation sub-panel

**Files:**
- Modify: `pushkey.py` — add `_render_rotate_subpanel` and `_show_rotate_subpanel` methods
- Modify: `pushkey.py` — add `_rotate_result` state var

- [ ] **Step 1: Add `_show_rotate_subpanel` method**

After `_inline_inject`, add:

```python
    def _show_rotate_subpanel(self, name: str):
        self._rotate_pending = True
        self._rotate_result = None
        self._render_key_rows()
```

- [ ] **Step 3: Add `_render_rotate_subpanel` method**

After `_show_rotate_subpanel`, add:

```python
    def _render_rotate_subpanel(self, parent_frame, name: str):
        """Amber strip with input + confirm + cancel, or green result strip."""
        if self._rotate_result is not None:
            # ── Result strip ──
            strip = ctk.CTkFrame(parent_frame, fg_color=C["green_bg"],
                                 corner_radius=0, border_width=0)
            strip.pack(fill="x", padx=0, pady=(1, 0))

            row = ctk.CTkFrame(strip, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=7)

            ctk.CTkLabel(row, text="✓  Rotated", font=(_UI_FONT, 11, "bold"),
                         text_color=C["green"]).pack(side="left", padx=(0, 10))

            new_masked = "●" * min(len(self._rotate_result), 24)
            val_box = ctk.CTkFrame(row, fg_color=C["bg3"], corner_radius=4,
                                   border_width=1, border_color=C["border"])
            val_box.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(val_box, text=new_masked,
                         font=(_MONO_FONT, 11), text_color=C["accent"]).pack(
                side="left", padx=8, pady=3)

            copy_result_btn = make_btn(
                row, "⎘ Copy",
                lambda: None,
                fg_color=C["btn"], text_color=C["green"],
                width=60, height=24, border=False,
            )
            result_val = self._rotate_result
            copy_result_btn.configure(
                command=lambda: self.copy_key(result_val, flash_widget=copy_result_btn))
            copy_result_btn.pack(side="left", padx=(6, 0))

            dismiss_btn = make_btn(row, "✕", self._dismiss_rotate_result,
                                   fg_color="transparent", text_color=C["text3"],
                                   width=24, height=24, border=False)
            dismiss_btn.pack(side="right")

            # Auto-dismiss after 8 seconds
            self.after(8000, self._dismiss_rotate_result)
            return

        # ── Input strip ──
        strip = ctk.CTkFrame(parent_frame, fg_color=C["amber_bg"],
                             corner_radius=0, border_width=0)
        strip.pack(fill="x", padx=0, pady=(1, 0))

        ctk.CTkLabel(strip, text="↻  ROTATE KEY", font=(_UI_FONT, 9, "bold"),
                     text_color=C["amber"]).pack(anchor="w", padx=14, pady=(7, 2))

        inp_var = tk.StringVar()
        inp = ctk.CTkEntry(
            strip, textvariable=inp_var,
            font=(_MONO_FONT, 11),
            fg_color=C["bg3"], text_color=C["text"],
            border_color=C["amber"],
            placeholder_text="Paste new key value...",
        )
        inp.pack(fill="x", padx=14, pady=(0, 4))
        inp.focus_set()

        btn_row = ctk.CTkFrame(strip, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 8))

        def _confirm():
            new_val = inp_var.get().strip()
            if not new_val:
                return
            self._apply_rotation(name, new_val)
            self._rotate_pending = False
            self._rotate_result = new_val
            self._render_key_rows()

        def _cancel():
            self._rotate_pending = False
            self._rotate_result = None
            self._render_key_rows()

        make_btn(btn_row, "Confirm Rotate", _confirm,
                 fg_color=C["amber_bg"], text_color=C["amber"],
                 border=True, width=120, height=26).pack(side="left", padx=(0, 6))
        make_btn(btn_row, "Cancel", _cancel,
                 fg_color="transparent", text_color=C["text3"],
                 border=True, width=70, height=26).pack(side="left")
        ctk.CTkLabel(btn_row, text="Old value backed up to history",
                     font=(_UI_FONT, 9), text_color=C["text3"]).pack(
            side="right", padx=(0, 0))
```

- [ ] **Step 4: Add `_dismiss_rotate_result` method**

After `_render_rotate_subpanel`, add:

```python
    def _dismiss_rotate_result(self):
        self._rotate_pending = False
        self._rotate_result = None
        self._render_key_rows()
```

- [ ] **Step 5: Run the app and test the rotation flow**

```
python pushkey.py
```

- Expand a key row for a non-API key (not OpenAI/Anthropic/AWS)
- Click "↻ Rotate" → amber strip appears with input field
- Paste a fake value → click "Confirm Rotate" → green result strip appears
- Wait 8 seconds → strip auto-dismisses
- Verify old value was backed up: check the key's `history` list in the vault

- [ ] **Step 6: Run tests**

```
pytest -x
```

Expected: all 107 tests pass.

- [ ] **Step 7: Commit**

```
git add pushkey.py
git commit -m "feat: add inline rotation sub-panel with confirm and result strip"
```

---

## Task 6: Copy flash feedback

**Files:**
- Modify: `pushkey.py:5771-5775` (`copy_key` method)

- [ ] **Step 1: Modify `copy_key` to accept `flash_widget`**

Find `copy_key` at line 5771:

```python
    def copy_key(self, value):
        self.clipboard_clear()
        self.clipboard_append(value)
        job_id = self.after(30000, self.clipboard_clear)
        self._clipboard_jobs.append(job_id)
```

Replace with:

```python
    def copy_key(self, value, flash_widget=None):
        self.clipboard_clear()
        self.clipboard_append(value)
        job_id = self.after(30000, self.clipboard_clear)
        self._clipboard_jobs.append(job_id)
        if flash_widget:
            try:
                flash_widget.configure(text="✓  Copied", text_color=C["green"])
                self.after(1500, lambda: flash_widget.configure(
                    text="⎘  Copy Value", text_color=C["accent"]))
            except Exception:
                pass  # widget may have been destroyed if row re-rendered
```

- [ ] **Step 2: Run tests**

```
pytest -x
```

Expected: all 107 tests pass. `copy_key` signature is backward-compatible (new param is keyword-only default).

- [ ] **Step 3: Manually verify flash**

```
python pushkey.py
```

- Expand a key row
- Click "⎘ Copy Value" → button briefly shows "✓ Copied" in green, then resets after 1.5s

- [ ] **Step 4: Commit**

```
git add pushkey.py
git commit -m "feat: add copy flash feedback to copy_key"
```

---

## Task 7: Clear expanded state on search, group-by, and tab switch

**Files:**
- Modify: `pushkey.py:4923-4926` (`_on_search_change`)
- Modify: `pushkey.py:4996-4999` (`_toggle_group_by`)
- Modify: `pushkey.py` — `_switch_tab` or equivalent nav handler

- [ ] **Step 1: Clear state in `_on_search_change`**

Find `_on_search_change` at line 4923:

```python
    def _on_search_change(self, *_):
        if self._search_debounce_id:
            self.after_cancel(self._search_debounce_id)
        self._search_debounce_id = self.after(200, self._render_key_rows)
```

Replace with:

```python
    def _on_search_change(self, *_):
        if self._search_debounce_id:
            self.after_cancel(self._search_debounce_id)
        self._expanded_key = None
        self._rotate_pending = False
        self._rotate_result = None
        self._search_debounce_id = self.after(200, self._render_key_rows)
```

- [ ] **Step 2: Clear state in `_toggle_group_by`**

Find `_toggle_group_by` at line 4996:

```python
    def _toggle_group_by(self):
        self._group_by = "category" if self._group_by == "file" else "file"
        self._collapsed_groups.clear()
```

Replace with:

```python
    def _toggle_group_by(self):
        self._group_by = "category" if self._group_by == "file" else "file"
        self._collapsed_groups.clear()
        self._expanded_key = None
        self._rotate_pending = False
        self._rotate_result = None
```

- [ ] **Step 3: Clear state in `_nav_switch` when leaving the keys tab**

Find `_nav_switch` at line 2303:

```python
    def _nav_switch(self, key: str):
        self._active_nav.set(key)
        for k, btn in self._nav_btns.items():
```

Add state clearing at the top of the method, before existing logic:

```python
    def _nav_switch(self, key: str):
        # Clear accordion state whenever tab changes
        if key != "keys":
            self._expanded_key = None
            self._rotate_pending = False
            self._rotate_result = None
        self._active_nav.set(key)
        for k, btn in self._nav_btns.items():
```

- [ ] **Step 4: Run tests**

```
pytest -x
```

Expected: all 107 tests pass.

- [ ] **Step 5: Manually verify state clearing**

```
python pushkey.py
```

- Expand a key row
- Type in the search box → row collapses
- Clear search → rows visible, none expanded
- Expand a row, click group-by toggle → row collapses
- Expand a row, click a different sidebar tab → row state cleared when returning

- [ ] **Step 6: Commit**

```
git add pushkey.py
git commit -m "feat: clear accordion state on search, group-by, and tab switch"
```

---

## Task 8: Final integration check

- [ ] **Step 1: Run full test suite**

```
pytest -v
```

Expected: 107 tests pass, 0 failures.

- [ ] **Step 2: Manual smoke test**

```
python pushkey.py
```

Verify each success criterion from the spec:

- [ ] Clicking a key row expands it inline; clicking again collapses it
- [ ] Opening row B while row A is open collapses A automatically
- [ ] Expanded panel shows value (masked), provider, env, created, rotated, projects
- [ ] Category accent bar (3px left border) uses the correct `CAT_COLORS` color
- [ ] Rotate button (non-API key) shows inline sub-panel with input + confirm + cancel
- [ ] Confirm rotation calls `_apply_rotation`, shows green result strip, auto-dismisses after 8s
- [ ] Copy button flashes "✓ Copied" green for 1.5s without triggering a re-render
- [ ] API auto-rotation (OpenAI/Anthropic/AWS) still opens the existing modal
- [ ] `show_key_detail` modal still works from Timeline/Lifecycle tab and Dashboard forecast
- [ ] Search, group-by toggle, and tab switch all collapse any open row

- [ ] **Step 3: Final commit**

```
git add pushkey.py
git commit -m "feat: swagger-inspired UX complete — accordion All Keys tab"
```
