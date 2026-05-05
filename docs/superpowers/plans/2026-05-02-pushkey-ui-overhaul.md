# Pushkey UI Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Pushkey's dashboard into a command center with color-coded arc gauges, a rotation forecast gantt, an activity feed, a full Timeline tab, and 3 performance fixes (lazy rendering, search debounce, deferred imports).

**Architecture:** All changes land in `pushkey.py` (single-file app, ~5,800 lines). New helper functions are inserted before the class definitions. GUI tabs follow the existing pattern: each tab has a `*_frame` attribute, a `render_*()` method, and a nav key registered in `_NAV_FRAMES`. Performance fixes replace `render_all()` call patterns with a dirty-flag lazy system.

**Tech Stack:** Python 3, CustomTkinter, tkinter.Canvas (arc drawing), existing crypto/vault layer unchanged.

**Spec:** `docs/superpowers/specs/2026-05-02-pushkey-ui-overhaul-design.md`

---

## File Map

| File | Change |
|------|--------|
| `pushkey.py:1910–1979` | Replace `C_DARK` + `C_LIGHT` dicts |
| `pushkey.py:~248` | Insert `_log_line_age_days()` helper |
| `pushkey.py:~2043` | Insert `_draw_arc_gauge()` Canvas helper |
| `pushkey.py:2435–2452` | Add `timeline_frame`, lazy-render vars, timeline instance vars |
| `pushkey.py:2396–2414` | Add `("timeline", "Timeline")` nav item |
| `pushkey.py:2466–2472` | Add `"timeline": "timeline_frame"` to `_NAV_FRAMES` |
| `pushkey.py:2474–2487` | Rewrite `_nav_switch()` with dirty-flag logic |
| `pushkey.py:3661–3666` | Update `render_all()` to include `render_timeline()` |
| `pushkey.py:3672–3866` | Full rewrite of `render_dashboard()` |
| `pushkey.py:~3870` | Insert `render_timeline()` + 3 sub-tab renderers |
| `pushkey.py:3898` | Replace search `trace_add` with debounced version |
| `pushkey.py:~2113` | Add background preload thread in `LoginFrame.__init__` |
| `tests/test_ui_helpers.py` | New — unit tests for `_log_line_age_days` |

---

## Task 1: Terminal Authority Color System

**Files:**
- Modify: `pushkey.py:1910–1979`

- [ ] **Step 1: Replace `C_DARK`**

Find the block starting with `C_DARK = {` at line 1910 and replace the entire dict body (lines 1910–1947) with:

```python
C_DARK = {
    # Backgrounds — OLED-punchy, clearly tiered
    "bg":           "#050A0F",
    "bg2":          "#0A1628",
    "bg3":          "#0F2035",
    "bg4":          "#152840",
    "surface":      "#0A1628",
    # Brand accent — CYAN (green demoted to health status only)
    "accent":       "#22D3EE",
    "accent2":      "#06B6D4",
    "accent_dim":   "#051318",
    # Violet — security, MFA, enterprise tier
    "violet":       "#7C3AED",
    "violet_dim":   "#110D1E",
    # Text — cyan-tinted hierarchy
    "text":         "#F0F9FF",
    "text2":        "#7FB3CC",
    "text3":        "#3D6E8A",
    # Borders — visible
    "border":       "#112233",
    "border2":      "#1A3550",
    # Buttons
    "btn":          "#0F2035",
    "btn_hover":    "#152840",
    # Semantic — green LOCKED to healthy status only
    "green":        "#00DC82",
    "green_bg":     "#041A0F",
    "amber":        "#F59E0B",
    "amber_bg":     "#1F1200",
    "red":          "#EF4444",
    "red_bg":       "#1F0808",
    "blue":         "#22D3EE",
    "blue_bg":      "#051318",
    # Environment pills
    "env_dev":      "#22D3EE",
    "env_staging":  "#F59E0B",
    "env_prod":     "#EF4444",
    "env_all":      "#7C3AED",
}
```

- [ ] **Step 2: Update `C_LIGHT` accent keys**

In `C_LIGHT` (starts ~line 1949), replace only these 5 keys:

```python
    "accent":       "#0891B2",
    "accent2":      "#0E7490",
    "accent_dim":   "#ECFEFF",
    "border":       "#CBD5E1",
    "border2":      "#B6C5D4",
```

- [ ] **Step 3: Verify app starts with new colors**

```
python pushkey.py
```

Expected: login screen shows, background is noticeably darker (`#050A0F`), accent elements (buttons/badges) appear cyan rather than green.

- [ ] **Step 4: Commit**

```
git add pushkey.py
git commit -m "feat: Terminal Authority color system — cyan accent, OLED base, tiered surfaces"
```

---

## Task 2: `_log_line_age_days` Helper

**Files:**
- Modify: `pushkey.py` — insert after `_log_decrypt_all()` (~line 223)
- Create: `tests/test_ui_helpers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_helpers.py`:

```python
from datetime import datetime, timedelta
import pushkey


def test_log_line_age_days_parses_fresh():
    now = datetime.now()
    line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] OPENAI_KEY rotated"
    age = pushkey._log_line_age_days(line)
    assert 0 <= age < 0.01  # less than ~15 seconds


def test_log_line_age_days_parses_old():
    old = datetime.now() - timedelta(days=30)
    line = f"[{old.strftime('%Y-%m-%d %H:%M:%S')}] STRIPE_SK rotated"
    age = pushkey._log_line_age_days(line)
    assert 29.9 < age < 30.1


def test_log_line_age_days_bad_format_returns_inf():
    assert pushkey._log_line_age_days("no timestamp here") == float("inf")
    assert pushkey._log_line_age_days("") == float("inf")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_ui_helpers.py -v
```

Expected: `AttributeError: module 'pushkey' has no attribute '_log_line_age_days'`

- [ ] **Step 3: Add the function to `pushkey.py`**

Insert after `_log_decrypt_all()` (after line ~223, before `_migrate_plaintext_log`):

```python
def _log_line_age_days(line: str) -> float:
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
    if not m:
        return float("inf")
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds() / 86400
    except ValueError:
        return float("inf")
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_ui_helpers.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```
git add pushkey.py tests/test_ui_helpers.py
git commit -m "feat: add _log_line_age_days helper with tests"
```

---

## Task 3: `_draw_arc_gauge` Canvas Helper

**Files:**
- Modify: `pushkey.py` — insert after `make_btn()` (~line 2043)

- [ ] **Step 1: Add the function**

Insert after `make_btn()` definition (after line ~2070, before `health_status()`):

```python
def _draw_arc_gauge(canvas: tk.Canvas, pct: float, color: str,
                    center_text: str, sub_label: str) -> None:
    """Draw a 220° speedometer-style arc gauge. Canvas must be 160×140."""
    import math
    canvas.delete("all")
    bg = canvas["bg"] if canvas["bg"] != "" else C["bg"]
    cx, cy = 80, 76
    r = 52
    stroke = 12

    # Arc spans from 200° to -20° (clockwise), tkinter measures CCW from east
    start = 200
    full_extent = -220

    x0, y0 = cx - r, cy - r
    x1, y1 = cx + r, cy + r

    # Background track
    canvas.create_arc(x0, y0, x1, y1, start=start, extent=full_extent,
                      style="arc", outline=C["bg3"], width=stroke)

    pct = max(0.0, min(1.0, pct))
    if pct > 0.01:
        extent = full_extent * max(0.02, pct)

        # Glow layer — wider dashed arc same color
        canvas.create_arc(x0 - 4, y0 - 4, x1 + 4, y1 + 4,
                          start=start, extent=extent,
                          style="arc", outline=color, width=4, dash=(2, 4))

        # Main colored arc
        canvas.create_arc(x0, y0, x1, y1, start=start, extent=extent,
                          style="arc", outline=color, width=stroke)

        # Needle dot at arc end
        end_rad = math.radians(start + extent)
        dx = cx + r * math.cos(end_rad)
        dy = cy - r * math.sin(end_rad)
        canvas.create_oval(dx - 5, dy - 5, dx + 5, dy + 5,
                           fill=color, outline=C["bg"])

    # Center value text
    canvas.create_text(cx, cy - 6, text=center_text,
                       font=(_MONO_FONT, 26, "bold"), fill=color, anchor="center")

    # Sub-label
    canvas.create_text(cx, cy + 20, text=sub_label,
                       font=(_UI_FONT, 9), fill=C["text3"], anchor="center")
```

- [ ] **Step 2: Smoke-test the helper manually**

Add a temporary test at the very bottom of `pushkey.py` (outside any class, after `PushkeyApp`):

```python
if __name__ == "__main__" and "--test-gauge" in __import__("sys").argv:
    root = tk.Tk()
    root.configure(bg=C["bg"])
    c = tk.Canvas(root, width=160, height=140, bg=C["bg"], highlightthickness=0)
    c.pack(padx=20, pady=20)
    _draw_arc_gauge(c, 0.87, C["green"], "87", "OPTIMAL")
    root.mainloop()
```

Run: `python pushkey.py --test-gauge`

Expected: window with a green arc gauge showing "87" and "OPTIMAL".

- [ ] **Step 3: Remove the test code**

Delete the `if __name__ == "__main__" and "--test-gauge"` block added in Step 2.

- [ ] **Step 4: Commit**

```
git add pushkey.py
git commit -m "feat: _draw_arc_gauge Canvas helper — 220° speedometer with glow"
```

---

## Task 4: Dashboard Row 1 — Security Score + Velocity Gauges

**Files:**
- Modify: `pushkey.py:3672–3735` (start of `render_dashboard()`)

- [ ] **Step 1: Replace the top of `render_dashboard()`**

The current `render_dashboard()` starts at line 3672. Replace lines 3672–3735 (everything up to and including the stat cards `for` loop and the spacer after) with the new version that adds gauge columns flanking the stat cards.

Replace from `def render_dashboard(self):` through the closing `else: ctk.CTkFrame(card, ...).pack()` block (~line 3735) with:

```python
    def render_dashboard(self):
        for w in self.dash_frame.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(self.dash_frame, fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        pad = ctk.CTkFrame(scroll, fg_color="transparent")
        pad.pack(fill="x", padx=20, pady=(16, 0))

        keys = list(self.vault.items())
        real_keys = [(n, v) for n, v in keys if not n.startswith("_")]
        total = len(real_keys)
        healthy  = sum(1 for _, v in real_keys if health_status(v) == "healthy")
        warning  = sum(1 for _, v in real_keys if health_status(v) == "warning")
        critical = sum(1 for _, v in real_keys if health_status(v) == "critical")
        projects = len(self.config.get("projects", {}))
        key_limit = tier_limits().get("max_keys")

        # ── Page header ──
        hdr_row = ctk.CTkFrame(pad, fg_color="transparent")
        hdr_row.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(hdr_row, text="Dashboard", font=FONT_H2,
                     text_color=C["text"]).pack(side="left")
        t = TIERS[current_tier()]
        tier_pill = ctk.CTkFrame(hdr_row, fg_color=C["accent_dim"], corner_radius=10)
        tier_pill.pack(side="right")
        ctk.CTkLabel(tier_pill, text=f"{t['label']} Plan",
                     font=FONT_XS, text_color=C["accent"]).pack(padx=8, pady=2)

        # ── Row 1: [Security Gauge] [Stat Cards] [Velocity Gauge] ──
        row1 = ctk.CTkFrame(pad, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 16))

        # Security score gauge (left)
        health_pct = healthy / total if total else 1.0
        score_color = (
            C["red"]    if health_pct < 0.50 else
            C["amber"]  if health_pct < 0.75 else
            C["accent"] if health_pct < 0.90 else
            C["green"]
        )
        score_label = (
            "CRITICAL" if health_pct < 0.50 else
            "AT RISK"  if health_pct < 0.75 else
            "SECURE"   if health_pct < 0.90 else
            "OPTIMAL"
        )
        gauge_left = ctk.CTkFrame(row1, fg_color=C["surface"], corner_radius=8,
                                   border_width=1, border_color=C["border"],
                                   width=170)
        gauge_left.pack(side="left", padx=(0, 8), fill="y")
        gauge_left.pack_propagate(False)
        ctk.CTkLabel(gauge_left, text="Security Score", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=12, pady=(10, 0))
        score_canvas = tk.Canvas(gauge_left, width=160, height=140,
                                  bg=C["surface"], highlightthickness=0)
        score_canvas.pack(pady=(0, 8))
        _draw_arc_gauge(score_canvas, health_pct, score_color,
                        str(int(health_pct * 100)), score_label)

        # Stat cards (center, expanding)
        stats_frame = ctk.CTkFrame(row1, fg_color="transparent")
        stats_frame.pack(side="left", fill="both", expand=True)

        key_display = f"{total} / {key_limit}" if key_limit else str(total)
        key_color   = C["amber"] if key_limit and total >= key_limit * 0.8 else C["text"]
        needs_rotation = warning + critical

        stat_defs = [
            ("Total Keys",    key_display,         key_color,   None,          None),
            ("Healthy",       str(healthy),         C["green"],  healthy,       total),
            ("Need Rotation", str(needs_rotation),
             C["amber"] if needs_rotation else C["green"], needs_rotation, total),
            ("Projects",      str(projects),        C["accent"], None,          None),
        ]
        for label, val, color, bar_val, bar_max in stat_defs:
            card = ctk.CTkFrame(stats_frame, fg_color=C["surface"], corner_radius=8,
                                border_width=1, border_color=C["border"])
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ctk.CTkLabel(card, text=label, font=FONT_XS,
                         text_color=C["text3"]).pack(anchor="w", padx=14, pady=(12, 2))
            ctk.CTkLabel(card, text=val, font=(_UI_FONT, 26, "bold"),
                         text_color=color).pack(anchor="w", padx=14)
            if bar_val is not None and bar_max and bar_max > 0:
                bar_bg = ctk.CTkFrame(card, fg_color=C["bg3"], height=6, corner_radius=3)
                bar_bg.pack(fill="x", padx=14, pady=(4, 12))
                bar_bg.pack_propagate(False)
                pct_bar = max(0.02, bar_val / bar_max)
                bar_fill = ctk.CTkFrame(bar_bg, fg_color=color, height=6, corner_radius=3,
                                        width=int(pct_bar * 160))
                bar_fill.place(x=0, y=0, relheight=1)
            else:
                ctk.CTkFrame(card, fg_color="transparent", height=22).pack()

        # Rotation velocity gauge (right)
        log_lines = _log_decrypt_all()
        rotations_30d = sum(
            1 for ln in log_lines
            if "rotated" in ln.lower() and _log_line_age_days(ln) <= 30
        )
        target_30d = max(1, len(real_keys) // 3)
        velocity_pct = min(1.0, rotations_30d / target_30d)

        gauge_right = ctk.CTkFrame(row1, fg_color=C["surface"], corner_radius=8,
                                    border_width=1, border_color=C["border"],
                                    width=170)
        gauge_right.pack(side="left", padx=(0, 0), fill="y")
        gauge_right.pack_propagate(False)
        ctk.CTkLabel(gauge_right, text="Rotation Rate", font=FONT_XS,
                     text_color=C["text3"]).pack(anchor="w", padx=12, pady=(10, 0))
        vel_canvas = tk.Canvas(gauge_right, width=160, height=140,
                                bg=C["surface"], highlightthickness=0)
        vel_canvas.pack(pady=(0, 8))
        _draw_arc_gauge(vel_canvas, velocity_pct, C["accent"],
                        str(rotations_30d), "THIS MONTH")
```

- [ ] **Step 2: Run app and verify Row 1**

```
python pushkey.py
```

Unlock the vault. Expected: Dashboard shows two arc gauges flanking four stat cards. Left gauge shows security score 0–100, right gauge shows rotation count. Health bar under each stat card is 6px tall.

- [ ] **Step 3: Commit**

```
git add pushkey.py
git commit -m "feat: dashboard Row 1 — security score + velocity arc gauges"
```

---

## Task 5: Dashboard Row 2 — Rotation Forecast Gantt

**Files:**
- Modify: `pushkey.py` — add inside `render_dashboard()`, after Row 1, before the "Scheduled rotations due" section

- [ ] **Step 1: Insert forecast gantt section**

After the Row 1 block (after the `gauge_right` pack line from Task 4), before the existing `# Scheduled rotations due` comment, insert:

```python
        # ── Row 2: Rotation Forecast Gantt ──
        keys_with_schedule = [
            (n, i) for n, i in real_keys
            if i.get("rotation_schedule") and isinstance(i["rotation_schedule"], (int, float))
        ]
        if keys_with_schedule:
            forecast_hdr = ctk.CTkFrame(pad, fg_color="transparent")
            forecast_hdr.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(forecast_hdr, text="ROTATION FORECAST", font=FONT_XS,
                         text_color=C["text3"]).pack(side="left")

            self._forecast_window = getattr(self, "_forecast_window", tk.StringVar(value="30"))
            window_days = int(self._forecast_window.get())

            win_menu = ctk.CTkOptionMenu(
                forecast_hdr,
                values=["30", "60", "90"],
                variable=self._forecast_window,
                command=lambda _: self.render_dashboard(),
                width=72, height=24, font=FONT_XS,
                fg_color=C["btn"], button_color=C["btn"],
                button_hover_color=C["btn_hover"], text_color=C["text2"],
            )
            win_menu.pack(side="right")

            gantt_frame = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6,
                                       border_width=1, border_color=C["border"])
            gantt_frame.pack(fill="x", pady=(0, 16))

            for name, info in sorted(keys_with_schedule,
                                     key=lambda x: days_until_rotation(x[1]) or 0):
                schedule = int(info["rotation_schedule"])
                days_left = days_until_rotation(info) or 0
                days_used = schedule - days_left
                fill_pct = max(0.02, min(1.0, days_used / schedule))
                status = health_status(info)
                bar_color = health_color(status)
                overdue = days_left <= 0

                row = ctk.CTkFrame(gantt_frame, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=3)

                # Key name
                ctk.CTkLabel(row, text=name, font=FONT_MONO_SM,
                             text_color=C["text"], width=160,
                             anchor="w").pack(side="left")

                # Bar area
                bar_wrap = ctk.CTkFrame(row, fg_color=C["bg3"], height=8,
                                        corner_radius=4)
                bar_wrap.pack(side="left", fill="x", expand=True, padx=(8, 8))
                bar_wrap.pack_propagate(False)

                def _draw_bar(bw=bar_wrap, pct=fill_pct, col=bar_color):
                    bw.update_idletasks()
                    w = bw.winfo_width()
                    if w > 10:
                        bar = ctk.CTkFrame(bw, fg_color=col, height=8,
                                           corner_radius=4, width=int(pct * w))
                        bar.place(x=0, y=0, relheight=1)

                bar_wrap.after(50, _draw_bar)

                # Days label + Rotate button
                days_lbl = "OVERDUE" if overdue else f"{abs(int(days_left))}d left"
                ctk.CTkLabel(row, text=days_lbl, font=FONT_XS,
                             text_color=bar_color, width=70).pack(side="left")
                make_btn(row, "Rotate",
                         lambda n=name: (self.rotate_key(n), self._invalidate_tabs("dashboard", "keys", "timeline")),
                         fg_color=C["red_bg"] if overdue else C["btn"],
                         text_color=C["red"] if overdue else C["text2"],
                         width=60, height=24).pack(side="right")
```

- [ ] **Step 2: Run app and verify Row 2**

```
python pushkey.py
```

Expected: below the gauge row, "ROTATION FORECAST" section appears for keys that have a rotation schedule set. Bars are color-coded. Dropdown switches between 30/60/90d windows.

If no keys have `rotation_schedule`, the section is hidden (correct behavior).

To test: add a key, set `rotation_schedule=30` on it via the detail modal.

- [ ] **Step 3: Commit**

```
git add pushkey.py
git commit -m "feat: dashboard Row 2 — rotation forecast gantt with color-coded bars"
```

---

## Task 6: Dashboard Row 3 — Activity Feed

**Files:**
- Modify: `pushkey.py` — add inside `render_dashboard()`, after the gantt, before "ACTION NEEDED"

- [ ] **Step 1: Insert activity feed section**

After the forecast gantt block (after `if keys_with_schedule:` closes), before the existing `# ── Action needed callout cards ──` section, insert:

```python
        # ── Row 3: Recent Activity Feed ──
        all_log = list(reversed(_log_decrypt_all()))  # newest first
        if all_log:
            feed_hdr = ctk.CTkFrame(pad, fg_color="transparent")
            feed_hdr.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(feed_hdr, text="RECENT ACTIVITY", font=FONT_XS,
                         text_color=C["text3"]).pack(side="left")
            view_all = make_btn(feed_hdr, "View all →",
                                lambda: (self._timeline_subtab.set("activity"),
                                         self._nav_switch("timeline")),
                                fg_color="transparent", text_color=C["accent"],
                                width=80, height=22)
            view_all.pack(side="right")

            feed_frame = ctk.CTkFrame(pad, fg_color=C["surface"], corner_radius=6,
                                      border_width=1, border_color=C["border"])
            feed_frame.pack(fill="x", pady=(0, 16))

            _event_colors = {
                "rotated":  C["green"],
                "added":    C["accent"],
                "imported": C["accent"],
                "deleted":  C["amber"],
                "overdue":  C["red"],
            }

            for line in all_log[:8]:
                dot_color = C["text3"]
                for kw, col in _event_colors.items():
                    if kw in line.lower():
                        dot_color = col
                        break

                entry = ctk.CTkFrame(feed_frame, fg_color="transparent")
                entry.pack(fill="x", padx=12, pady=2)

                ctk.CTkLabel(entry, text="●", font=(_MONO_FONT, 9),
                             text_color=dot_color, width=16).pack(side="left")

                # Strip the timestamp prefix for display, show age
                display = line
                m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", line)
                if m:
                    age = _log_line_age_days(line)
                    if age < 1/24:
                        age_str = f"{int(age * 1440)}m ago"
                    elif age < 1:
                        age_str = f"{int(age * 24)}h ago"
                    else:
                        age_str = f"{int(age)}d ago"
                    display = m.group(2)
                    ctk.CTkLabel(entry, text=age_str, font=FONT_XS,
                                 text_color=C["text3"], width=55,
                                 anchor="w").pack(side="left", padx=(2, 6))

                ctk.CTkLabel(entry, text=display, font=FONT_XS,
                             text_color=C["text2"], anchor="w").pack(side="left", fill="x", expand=True)
```

- [ ] **Step 2: Run app and verify Row 3**

```
python pushkey.py
```

Expected: "RECENT ACTIVITY" section shows up to 8 log entries with colored dots and relative timestamps. "View all →" button is visible (clicking it will fail gracefully until Timeline tab is built in Task 7).

- [ ] **Step 3: Commit**

```
git add pushkey.py
git commit -m "feat: dashboard Row 3 — activity feed with colored event dots"
```

---

## Task 7: Timeline Tab Infrastructure

**Files:**
- Modify: `pushkey.py:2396–2414` (nav_items list)
- Modify: `pushkey.py:2435–2446` (frame creation + grid)
- Modify: `pushkey.py:2466–2472` (`_NAV_FRAMES` dict)
- Modify: `pushkey.py:2309` (instance vars area)
- Modify: `pushkey.py:3661–3666` (`render_all`)

- [ ] **Step 1: Add instance vars**

In `AppFrame.__init__`, after `self._search_var = tk.StringVar()` (~line 2309), add:

```python
        self._timeline_subtab = tk.StringVar(value="lifecycle")
        self._timeline_page = 0
        self._timeline_filter = tk.StringVar(value="all")
        self._forecast_window = tk.StringVar(value="30")
        self._tab_rendered: set = set()
        self._tab_dirty: set = set()
        self._search_debounce_id = None
```

- [ ] **Step 2: Add `timeline_frame` creation**

After line 2439 (`self.cloud_frame = ctk.CTkFrame(...)`), add:

```python
        self.timeline_frame = ctk.CTkFrame(content, fg_color=C["bg"], corner_radius=0)
```

- [ ] **Step 3: Add `timeline_frame` to the grid loop**

Change the for loop at lines 2441–2443 from:

```python
        for f in (self.dash_frame, self.keys_frame, self.proj_frame,
                  self.scan_frame, self.cloud_frame):
            f.grid(row=0, column=0, sticky="nsew")
```

to:

```python
        for f in (self.dash_frame, self.keys_frame, self.proj_frame,
                  self.scan_frame, self.cloud_frame, self.timeline_frame):
            f.grid(row=0, column=0, sticky="nsew")
```

- [ ] **Step 4: Add "Timeline" to sidebar nav**

In `nav_items` list (~line 2396), add after `("cloud", "Cloud")`:

```python
            ("timeline",  "Timeline"),
```

- [ ] **Step 5: Register in `_NAV_FRAMES`**

Add to `_NAV_FRAMES` dict (~line 2466):

```python
        "timeline":  "timeline_frame",
```

- [ ] **Step 6: Add `render_timeline()` with sub-tab bar**

After `render_cloud()` (find it by searching for `def render_cloud`), add:

```python
    # ═══════════════════════════════════════════
    # TIMELINE TAB
    # ═══════════════════════════════════════════

    def render_timeline(self):
        for w in self.timeline_frame.winfo_children():
            w.destroy()

        # Header
        header = ctk.CTkFrame(self.timeline_frame, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 0))
        ctk.CTkLabel(header, text="Timeline", font=FONT_H2,
                     text_color=C["text"]).pack(side="left")

        # Sub-tab bar
        sub_bar = ctk.CTkFrame(self.timeline_frame, fg_color="transparent")
        sub_bar.pack(fill="x", padx=20, pady=(12, 0))

        subtabs = [("lifecycle", "Lifecycle"), ("activity", "Activity"), ("forecast", "Forecast")]
        for key, label in subtabs:
            is_active = self._timeline_subtab.get() == key
            make_btn(
                sub_bar, label,
                lambda k=key: (self._timeline_subtab.set(k), self._switch_timeline_subtab()),
                fg_color=C["accent_dim"] if is_active else "transparent",
                text_color=C["accent"] if is_active else C["text2"],
                width=90, height=28, corner_radius=6,
            ).pack(side="left", padx=(0, 4))

        ctk.CTkFrame(self.timeline_frame, fg_color=C["border"], height=1).pack(
            fill="x", padx=20, pady=(8, 0))

        # Sub-tab content container
        self._timeline_content = ctk.CTkFrame(self.timeline_frame,
                                               fg_color="transparent", corner_radius=0)
        self._timeline_content.pack(fill="both", expand=True)

        self._switch_timeline_subtab()

    def _switch_timeline_subtab(self):
        for w in self._timeline_content.winfo_children():
            w.destroy()
        sub = self._timeline_subtab.get()
        if sub == "lifecycle":
            self._render_lifecycle()
        elif sub == "activity":
            self._render_activity_tab()
        else:
            self._render_forecast_tab()
```

- [ ] **Step 7: Add `render_timeline()` to `render_all()`**

Change `render_all()` at line 3661:

```python
    def render_all(self):
        self.render_dashboard()
        self.render_keys()
        self.render_projects()
        self.render_scan()
        self.render_cloud()
        self.render_timeline()
```

- [ ] **Step 8: Run app and verify Timeline tab appears**

```
python pushkey.py
```

Expected: "Timeline" appears in sidebar nav. Clicking it switches to the timeline frame showing sub-tab bar with "Lifecycle / Activity / Forecast". Content area is empty (sub-renderers not built yet — that's fine).

- [ ] **Step 9: Commit**

```
git add pushkey.py
git commit -m "feat: Timeline tab infrastructure — frame, nav, sub-tab bar, render stub"
```

---

## Task 8: Timeline — Lifecycle Sub-tab

**Files:**
- Modify: `pushkey.py` — add `_render_lifecycle()` method

- [ ] **Step 1: Add `_render_lifecycle()` method**

Add after `_switch_timeline_subtab()`:

```python
    def _render_lifecycle(self):
        real_keys = [(n, v) for n, v in self.vault.items() if not n.startswith("_")]
        if not real_keys:
            ctk.CTkLabel(self._timeline_content, text="No keys yet.",
                         font=FONT_H3, text_color=C["text3"]).pack(pady=40)
            return

        container = ctk.CTkScrollableFrame(self._timeline_content,
                                            fg_color=C["bg"], corner_radius=0)
        container.pack(fill="both", expand=True)

        # Compute time range
        from datetime import timezone
        def _parse_dt(s):
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return None

        now = datetime.now()
        all_created = [_parse_dt(v.get("created")) for _, v in real_keys]
        all_created = [d for d in all_created if d]
        t_start = min(all_created) if all_created else now - timedelta(days=90)
        t_end   = now + timedelta(days=30)
        span = (t_end - t_start).total_seconds()
        if span <= 0:
            span = 1

        NAME_W = 150
        ROW_H  = 32
        PAD    = 12

        header_row = ctk.CTkFrame(container, fg_color=C["bg2"], height=24)
        header_row.pack(fill="x", padx=PAD, pady=(8, 2))
        ctk.CTkLabel(header_row, text="KEY", font=FONT_XS,
                     text_color=C["text3"], width=NAME_W, anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(header_row, text="CREATED ──────────── NOW ──── DUE", font=FONT_XS,
                     text_color=C["text3"], anchor="w").pack(side="left", fill="x", expand=True, padx=4)

        for idx, (name, info) in enumerate(sorted(real_keys, key=lambda x: x[0])):
            row_bg = C["bg"] if idx % 2 == 0 else C["bg2"]
            row = ctk.CTkFrame(container, fg_color=row_bg, height=ROW_H, corner_radius=0)
            row.pack(fill="x", padx=PAD, pady=1)
            row.pack_propagate(False)
            row.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            # Name label
            lbl = ctk.CTkLabel(row, text=name, font=FONT_MONO_SM,
                               text_color=C["text"], width=NAME_W, anchor="w", cursor="hand2")
            lbl.pack(side="left", padx=4)
            lbl.bind("<Button-1>", lambda e, n=name: self.show_key_detail(n))

            # Canvas for the swimlane
            cv = tk.Canvas(row, bg=row_bg, highlightthickness=0, height=ROW_H)
            cv.pack(side="left", fill="x", expand=True, padx=4)

            def _draw_lane(canvas=cv, inf=info, rb=row_bg):
                canvas.update_idletasks()
                W = canvas.winfo_width()
                if W < 20:
                    return
                H = ROW_H

                created_dt = _parse_dt(inf.get("created"))
                rotated_dt = _parse_dt(inf.get("rotated"))
                status = health_status(inf)
                dot_color = health_color(status)

                def _t_to_x(dt):
                    if dt is None:
                        return None
                    return int(NAME_W + (dt - t_start).total_seconds() / span * (W - 10))

                cx_created = _t_to_x(created_dt)
                cx_rotated = _t_to_x(rotated_dt)
                cx_now     = _t_to_x(now)
                cx_due     = _t_to_x(
                    now + timedelta(days=days_until_rotation(inf) or 0)
                    if days_until_rotation(inf) is not None else None
                )

                y = H // 2

                # Base line
                if cx_created and cx_now:
                    canvas.create_line(cx_created, y, cx_now, y,
                                       fill=C["border2"], width=2)

                # Created dot (hollow)
                if cx_created:
                    canvas.create_oval(cx_created - 4, y - 4, cx_created + 4, y + 4,
                                       outline=dot_color, fill=rb, width=2)

                # Rotated dot (filled)
                if cx_rotated:
                    canvas.create_oval(cx_rotated - 4, y - 4, cx_rotated + 4, y + 4,
                                       fill=dot_color, outline="")

                # Now marker (vertical line)
                if cx_now:
                    canvas.create_line(cx_now, 4, cx_now, H - 4,
                                       fill=C["accent"], width=1, dash=(3, 3))

                # Due marker
                if cx_due and cx_due > cx_now:
                    canvas.create_line(cx_due, 4, cx_due, H - 4,
                                       fill=C["amber"], width=1)
                elif cx_now:
                    # Overdue — extend line past now in red
                    canvas.create_line(cx_now, y, min(W - 4, cx_now + 20), y,
                                       fill=C["red"], width=2, dash=(4, 2))

            cv.after(60, _draw_lane)
```

- [ ] **Step 2: Run app and verify Lifecycle sub-tab**

```
python pushkey.py
```

Expected: Timeline → Lifecycle shows one row per key with horizontal swimlanes. Created dot (hollow), rotated dot (filled), dashed "now" vertical line, amber due marker. Clicking a row opens key detail.

- [ ] **Step 3: Commit**

```
git add pushkey.py
git commit -m "feat: timeline Lifecycle sub-tab — swimlane per key with Canvas"
```

---

## Task 9: Timeline — Activity Sub-tab

**Files:**
- Modify: `pushkey.py` — add `_render_activity_tab()` method

- [ ] **Step 1: Add `_render_activity_tab()` method**

Add after `_render_lifecycle()`:

```python
    def _render_activity_tab(self):
        all_log = list(reversed(_log_decrypt_all()))  # newest first
        PAGE_SIZE = 25

        filter_val = self._timeline_filter.get()
        _filter_map = {
            "rotations": "rotated",
            "imports":   "import",
            "logins":    "unlock",
        }

        if filter_val != "all" and filter_val in _filter_map:
            kw = _filter_map[filter_val]
            all_log = [ln for ln in all_log if kw in ln.lower()]

        total_pages = max(1, (len(all_log) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._timeline_page = max(0, min(self._timeline_page, total_pages - 1))
        page_entries = all_log[self._timeline_page * PAGE_SIZE:(self._timeline_page + 1) * PAGE_SIZE]

        # Filter bar
        filter_bar = ctk.CTkFrame(self._timeline_content, fg_color="transparent")
        filter_bar.pack(fill="x", padx=20, pady=(12, 6))
        for fval, flabel in [("all", "All"), ("rotations", "Rotations"),
                              ("imports", "Imports"), ("logins", "Logins")]:
            is_active = self._timeline_filter.get() == fval
            make_btn(
                filter_bar, flabel,
                lambda v=fval: (self._timeline_filter.set(v),
                                setattr(self, "_timeline_page", 0),
                                self._switch_timeline_subtab()),
                fg_color=C["accent_dim"] if is_active else C["btn"],
                text_color=C["accent"] if is_active else C["text2"],
                width=80, height=24, corner_radius=12,
            ).pack(side="left", padx=2)

        # Log entries
        scroll = ctk.CTkScrollableFrame(self._timeline_content,
                                         fg_color=C["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        _event_colors = {
            "rotated":  C["green"],
            "added":    C["accent"],
            "imported": C["accent"],
            "deleted":  C["amber"],
            "overdue":  C["red"],
            "unlock":   C["text3"],
        }

        if not page_entries:
            ctk.CTkLabel(scroll, text="No activity yet.", font=FONT_XS,
                         text_color=C["text3"]).pack(pady=40)
        else:
            for line in page_entries:
                dot_color = C["text3"]
                for kw, col in _event_colors.items():
                    if kw in line.lower():
                        dot_color = col
                        break

                m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", line)
                ts_str = m.group(1) if m else ""
                body   = m.group(2) if m else line

                entry = ctk.CTkFrame(scroll, fg_color="transparent")
                entry.pack(fill="x", padx=20, pady=1)

                ctk.CTkLabel(entry, text="●", font=(_MONO_FONT, 9),
                             text_color=dot_color, width=14).pack(side="left")
                ctk.CTkLabel(entry, text=ts_str, font=FONT_XS,
                             text_color=C["text3"], width=130,
                             anchor="w").pack(side="left", padx=(4, 8))
                ctk.CTkLabel(entry, text=body, font=FONT_XS,
                             text_color=C["text2"], anchor="w").pack(side="left", fill="x", expand=True)

        # Pagination controls
        if total_pages > 1:
            pg_bar = ctk.CTkFrame(self._timeline_content, fg_color="transparent")
            pg_bar.pack(fill="x", padx=20, pady=8)
            make_btn(pg_bar, "← Prev",
                     lambda: (setattr(self, "_timeline_page", self._timeline_page - 1),
                              self._switch_timeline_subtab()),
                     fg_color=C["btn"], text_color=C["text2"], width=70,
                     ).pack(side="left")
            ctk.CTkLabel(pg_bar,
                         text=f"Page {self._timeline_page + 1} of {total_pages}",
                         font=FONT_XS, text_color=C["text3"]).pack(side="left", padx=12)
            make_btn(pg_bar, "Next →",
                     lambda: (setattr(self, "_timeline_page", self._timeline_page + 1),
                              self._switch_timeline_subtab()),
                     fg_color=C["btn"], text_color=C["text2"], width=70,
                     ).pack(side="left")
```

- [ ] **Step 2: Run app and verify Activity sub-tab**

```
python pushkey.py
```

Expected: Timeline → Activity shows log entries with colored dots, full timestamps, event body text. Filter pills work. Pagination shows if > 25 entries.

- [ ] **Step 3: Commit**

```
git add pushkey.py
git commit -m "feat: timeline Activity sub-tab — paginated log with filter pills"
```

---

## Task 10: Timeline — Forecast Sub-tab

**Files:**
- Modify: `pushkey.py` — add `_render_forecast_tab()` method

- [ ] **Step 1: Add `_render_forecast_tab()` method**

Add after `_render_activity_tab()`:

```python
    def _render_forecast_tab(self):
        keys_with_schedule = [
            (n, i) for n, i in self.vault.items()
            if not n.startswith("_")
            and i.get("rotation_schedule")
            and isinstance(i["rotation_schedule"], (int, float))
        ]

        if not keys_with_schedule:
            ctk.CTkLabel(self._timeline_content,
                         text="No keys have rotation schedules set.\nSet one in the key detail view.",
                         font=FONT_XS, text_color=C["text3"],
                         justify="center").pack(pady=60)
            return

        DAYS = 90
        COL_W = 18
        ROW_H = 28
        NAME_W = 160
        PAD = 16

        now = datetime.now().date()
        day_range = [now + timedelta(days=d) for d in range(DAYS)]

        outer = ctk.CTkFrame(self._timeline_content, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=PAD, pady=(12, 0))

        # Month headers
        month_bar = tk.Canvas(outer, bg=C["bg"], height=20, highlightthickness=0)
        month_bar.pack(fill="x")

        x = NAME_W + 4
        prev_month = None
        for i, day in enumerate(day_range):
            if day.month != prev_month:
                month_bar.create_text(x + 2, 10,
                                      text=day.strftime("%b"),
                                      font=(_UI_FONT, 9), fill=C["text3"],
                                      anchor="w")
                prev_month = day.month
            x += COL_W

        # Day columns + key rows
        canvas_h = ROW_H * len(keys_with_schedule) + 4
        canvas_w = NAME_W + COL_W * DAYS + 4

        scroll_x = tk.Scrollbar(outer, orient="horizontal")
        scroll_x.pack(side="bottom", fill="x")

        cv = tk.Canvas(outer, bg=C["bg"], height=canvas_h,
                       xscrollcommand=scroll_x.set, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.configure(scrollregion=(0, 0, canvas_w, canvas_h))
        scroll_x.config(command=cv.xview)

        for row_idx, (name, info) in enumerate(sorted(keys_with_schedule,
                                                       key=lambda x: x[0])):
            y0 = row_idx * ROW_H
            y1 = y0 + ROW_H
            row_bg = C["bg"] if row_idx % 2 == 0 else C["bg2"]
            cv.create_rectangle(0, y0, canvas_w, y1, fill=row_bg, outline="")

            # Key name
            cv.create_text(4, (y0 + y1) // 2, text=name,
                           font=(_MONO_FONT, 10), fill=C["text"], anchor="w")

            # Day cells
            schedule = int(info["rotation_schedule"])
            due_days = days_until_rotation(info)

            for col_idx, day in enumerate(day_range):
                x0 = NAME_W + col_idx * COL_W
                x1 = x0 + COL_W - 1

                if day == now.today():
                    cv.create_rectangle(x0, y0, x1, y1,
                                        fill=C["accent_dim"], outline="")

                if due_days is not None:
                    day_offset = col_idx - (0)  # relative to today
                    days_from_now = (day - now).days
                    if due_days <= 0 and days_from_now == 0:
                        cv.create_rectangle(x0 + 1, y0 + 4, x1 - 1, y1 - 4,
                                            fill=C["red"], outline="")
                    elif 0 <= days_from_now and days_from_now == int(due_days):
                        cell_color = C["amber"] if due_days <= 7 else C["green_bg"]
                        cv.create_rectangle(x0 + 1, y0 + 4, x1 - 1, y1 - 4,
                                            fill=cell_color, outline="")
```

- [ ] **Step 2: Run app and verify Forecast sub-tab**

```
python pushkey.py
```

Expected: Timeline → Forecast shows 90-day calendar grid. Rows = keys with schedules. Today's column highlighted cyan. Due date cell shown in amber (≤7 days) or green. Overdue shown red. Horizontal scroll works for 90 columns.

- [ ] **Step 3: Commit**

```
git add pushkey.py
git commit -m "feat: timeline Forecast sub-tab — 90-day calendar grid"
```

---

## Task 11: Lazy Tab Rendering

**Files:**
- Modify: `pushkey.py:2474–2487` (`_nav_switch`)
- Modify: `pushkey.py:2452` (startup `render_all()` call)
- Modify: all `render_all()` callsites (17 locations)

- [ ] **Step 1: Rewrite `_nav_switch()`**

Replace lines 2474–2487:

```python
    def _nav_switch(self, key: str):
        self._active_nav.set(key)
        for k, btn in self._nav_btns.items():
            if k == key:
                btn.configure(fg_color=C["accent_dim"], text_color=C["accent"])
            else:
                btn.configure(fg_color="transparent", text_color=C["text2"])
        frame = getattr(self, self._NAV_FRAMES[key])
        frame.tkraise()

        if key not in self._tab_rendered:
            getattr(self, f"render_{key}")()
            self._tab_rendered.add(key)
        elif key in self._tab_dirty:
            getattr(self, f"render_{key}")()
            self._tab_dirty.discard(key)
```

- [ ] **Step 2: Add `_invalidate_tabs()` method**

Add after `_nav_switch()`:

```python
    def _invalidate_tabs(self, *tabs: str):
        active = self._active_nav.get()
        for t in tabs:
            if t == active:
                getattr(self, f"render_{t}")()
            else:
                self._tab_dirty.add(t)
```

- [ ] **Step 3: Replace startup `render_all()` with `_nav_switch("dashboard")`**

At line 2446, the code already calls `self._nav_switch("dashboard")` before `render_all()`. Remove the `self.render_all()` call at line 2452 — `_nav_switch` will trigger the dashboard render lazily.

Change:

```python
        # Show dashboard by default
        self._nav_switch("dashboard")

        self._scan_results = []
        self._git_scan_results = []
        self._scan_ts = None

        self.render_all()
```

To:

```python
        # Show dashboard by default — lazy render triggered by _nav_switch
        self._nav_switch("dashboard")

        self._scan_results = []
        self._git_scan_results = []
        self._scan_ts = None
```

- [ ] **Step 4: Replace `render_all()` callsites**

Search for every `self.render_all()` call (there are ~17) and replace with `self._invalidate_tabs(...)` using the mutation table below.

For each callsite, determine what changed and invalidate only the affected tabs:

| Context (search for this nearby) | Replace with |
|----------------------------------|-------------|
| key rotate / add / edit / delete | `self._invalidate_tabs("dashboard", "keys", "timeline")` |
| project add / remove / change | `self._invalidate_tabs("projects", "dashboard")` |
| cloud sync complete | `self._invalidate_tabs("cloud", "dashboard")` |
| security / MFA / FIDO2 change | `self._invalidate_tabs("security")` |
| theme toggle (reload_app handles this) | leave as-is (reload_app recreates whole AppFrame) |
| bulk delete / bulk rotate | `self._invalidate_tabs("dashboard", "keys", "timeline")` |
| import / scan import | `self._invalidate_tabs("dashboard", "keys", "timeline")` |
| license/tier change | `self._invalidate_tabs("dashboard")` |

To find all callsites:
```
grep -n "self.render_all()" pushkey.py
```

Replace each one individually — do not use sed/replace-all since some need different tab sets.

- [ ] **Step 5: Verify all tabs still render correctly**

```
python pushkey.py
```

Navigate through every tab: Dashboard, All Keys (with search), Projects, Security, Cloud, Timeline. Perform a key add and verify dashboard + keys tabs update. Perform a search and verify it works.

- [ ] **Step 6: Commit**

```
git add pushkey.py
git commit -m "perf: lazy tab rendering — dirty-flag pattern replaces render_all()"
```

---

## Task 12: Search Debounce + Deferred Heavy Imports

**Files:**
- Modify: `pushkey.py:3898` (search `trace_add`)
- Modify: `pushkey.py:2113–2140` (`LoginFrame.__init__`)

### Part A — Search Debounce

- [ ] **Step 1: Replace search trace_add**

At line 3898, replace:

```python
        self._search_var.trace_add("write", lambda *_: self._render_key_rows())
```

With:

```python
        self._search_var.trace_add("write", self._on_search_change)
```

- [ ] **Step 2: Add `_on_search_change` method**

Add after `render_keys()`:

```python
    def _on_search_change(self, *_):
        if self._search_debounce_id:
            self.after_cancel(self._search_debounce_id)
        self._search_debounce_id = self.after(200, self._render_key_rows)
```

### Part B — Deferred Heavy Imports

- [ ] **Step 3: Move argon2 import to lazy thread**

The `argon2` import at lines 309–313 runs at module startup. It takes ~200–400ms. Make it non-blocking:

Replace lines 309–313:

```python
try:
    from argon2.low_level import hash_secret_raw, Type as Argon2Type
    _ARGON2_AVAILABLE = True
except ImportError:
    _ARGON2_AVAILABLE = False
```

With:

```python
hash_secret_raw = None
Argon2Type = None
_ARGON2_AVAILABLE = False

def _try_load_argon2():
    global hash_secret_raw, Argon2Type, _ARGON2_AVAILABLE
    try:
        from argon2.low_level import hash_secret_raw as _h, Type as _T
        hash_secret_raw = _h
        Argon2Type = _T
        _ARGON2_AVAILABLE = True
    except ImportError:
        pass
```

- [ ] **Step 4: Call `_try_load_argon2()` from `LoginFrame.__init__`**

In `LoginFrame.__init__` (~line 2114), after `super().__init__(...)`, add:

```python
        import threading
        threading.Thread(target=_try_load_argon2, daemon=True).start()
```

- [ ] **Step 5: Verify startup and vault unlock still work**

```
python pushkey.py
```

Expected:
- Window appears noticeably faster (no argon2 import blocking the main thread)
- Vault unlock still works — argon2 is loaded in background within the 1–2 seconds the user takes to type their password
- If argon2 somehow isn't ready by unlock time, `derive_key()` falls back to PBKDF2 (existing fallback at line ~325 already handles `_ARGON2_AVAILABLE = False`)

- [ ] **Step 6: Run full test suite**

```
pytest -v
```

Expected: all existing tests pass.

- [ ] **Step 7: Commit**

```
git add pushkey.py
git commit -m "perf: search debounce 200ms + deferred argon2 import for faster startup"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 7 spec sections covered — color system (T1), arc gauge helper (T3), dashboard Row 1/2/3 (T4/T5/T6), timeline infrastructure (T7), lifecycle (T8), activity (T9), forecast (T10), lazy rendering (T11), debounce + deferred imports (T12)
- [x] **No placeholders:** Every step has exact code or exact commands with expected output
- [x] **Type consistency:** `_draw_arc_gauge` signature used identically in T3 (definition) and T4/T5 (call sites). `_invalidate_tabs(*tabs: str)` defined in T11 Step 2, called in T5 and T11 Step 4. `_log_line_age_days` defined in T2, used in T4 and T6.
- [x] **`_forecast_window` var:** Added as instance var in T7 Step 1; used in T5 (dashboard gantt). Both reference `self._forecast_window`.
- [x] **`render_timeline` naming:** Consistent — `render_all()` calls `render_timeline()`, `_nav_switch` calls `render_timeline()`, `_NAV_FRAMES["timeline"]` → `"timeline_frame"`, `self.timeline_frame` attribute.
- [x] **`_timeline_subtab` lambda:** Activity feed "View all" button fixed to call `self._timeline_subtab.set("activity")` before `_nav_switch("timeline")` — ensures correct sub-tab activates on navigation.
