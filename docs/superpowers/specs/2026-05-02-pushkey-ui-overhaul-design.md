# Pushkey UI Overhaul — Design Spec
**Date:** 2026-05-02  
**Branch:** build/ftmo-bot  
**Scope:** Dashboard command center, Terminal Authority color system, Timeline tab, performance fixes

---

## 1. Overview

Three coordinated improvements to `pushkey.py`:

1. **Dashboard overhaul** — two `tk.Canvas` arc gauges + rotation forecast gantt + activity feed
2. **Terminal Authority color system** — cyan brand accent, green locked to health-only, improved surface elevation
3. **Timeline tab** — new 6th nav item with Lifecycle / Activity / Forecast sub-tabs
4. **Performance** — lazy tab rendering, search debounce, deferred heavy imports

All changes land in `pushkey.py`. No new files, no new dependencies.

---

## 2. Color System — Terminal Authority

Replace `C_DARK` in `pushkey.py` (~line 1910). Maps 1:1 to existing keys — no callsite changes needed.

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

### C_LIGHT parallel update

| Key | Old | New |
|-----|-----|-----|
| `accent` | `#3B82F6` | `#0891B2` (dark cyan) |
| `accent2` | `#2563EB` | `#0E7490` |
| `accent_dim` | `#EFF6FF` | `#ECFEFF` |
| `border` | `#EEF2F7` | `#CBD5E1` (more visible) |
| `border2` | `#E2E8F0` | `#B6C5D4` |

### Gauge color bands (score → arc color)

| Score | Color | Hex |
|-------|-------|-----|
| 0–49% | Critical red | `#EF4444` |
| 50–74% | Warning amber | `#F59E0B` |
| 75–89% | Brand cyan | `#22D3EE` |
| 90–100% | Healthy green | `#00DC82` |

---

## 3. Dashboard Overhaul

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  [Security Score Arc]    [Stat Cards x4]    [Velocity Arc]       │  Row 1
├──────────────────────────────────────────────────────────────────┤
│  ROTATION FORECAST (30-day gantt)                    [30d ▾]     │  Row 2
├──────────────────────────────────────────────────────────────────┤
│  RECENT ACTIVITY (last 8 events)              [View all →]       │  Row 3
├──────────────────────────────────────────────────────────────────┤
│  ACTION NEEDED callout cards (existing, recolored)               │  Row 4
├──────────────────────────────────────────────────────────────────┤
│  ALL KEYS health list (existing, recolored)                      │  Row 5
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 Arc Gauge Helper

New function `_draw_arc_gauge(canvas, pct, color, center_text, sub_label)`:

```
canvas size: 160 × 140 px
arc sweep:   220° (starts at 160°, ends at -40°, counterclockwise)
arc width:   12px stroke
glow:        duplicate arc at width+4px, 25% opacity, same color
needle dot:  8px filled circle at arc tip
center text: JetBrains Mono 28 bold, color = arc color
sub_label:   IBM Plex Sans 10, C["text3"], uppercase
```

Signature:
```python
def _draw_arc_gauge(canvas: tk.Canvas, pct: float, color: str,
                    center_text: str, sub_label: str) -> None
```

- `pct` clamped to `[0.0, 1.0]`
- Background arc always drawn first in `C["bg3"]`
- Colored arc drawn over it
- Glow drawn under colored arc (z-order: bg arc → glow → color arc → dot → text)

### 3.2 Security Score Gauge

Position: left column of Row 1 (`width=160`, `height=140`)

Calculation:
```python
health_pct = healthy / total if total else 1.0
score_color = (
    C["red"]   if health_pct < 0.50 else
    C["amber"] if health_pct < 0.75 else
    C["accent"] if health_pct < 0.90 else
    C["green"]
)
score_label = (
    "CRITICAL" if health_pct < 0.50 else
    "AT RISK"  if health_pct < 0.75 else
    "SECURE"   if health_pct < 0.90 else
    "OPTIMAL"
)
center_text = f"{int(health_pct * 100)}"
```

### 3.3 Rotation Velocity Meter

Position: right column of Row 1 (`width=160`, `height=140`)

Always cyan `#22D3EE`.

Calculation:
```python
# Count rotations in last 30 days from audit log
rotations_30d = sum(
    1 for line in _log_decrypt_all()
    if "rotated" in line.lower()
    and _log_line_age_days(line) <= 30
)
target = max(1, len(real_keys) // 3)   # target: rotate ~1/3 of keys/month
velocity_pct = min(1.0, rotations_30d / target)
center_text = str(rotations_30d)
sub_label = "THIS MONTH"
```

Three tick marks on arc at positions: current (filled cyan dot), 30d-avg (hollow), target (hollow gold).

### 3.4 Rotation Forecast Gantt

Below stat cards. Only renders keys with `rotation_schedule` set.

```
ROTATION FORECAST                                         [30d ▾]
──────────────────────────────────────────────────────────────────
OPENAI_KEY    [████████████░░░░░░░░│]  8d left    [Rotate]
STRIPE_SK     [████████████████████│]  OVERDUE    [Rotate]  ← red
```

Implementation:
- `tk.Canvas` per row, height=28px, full-width minus padding
- Bar fill = `(schedule - days_remaining) / schedule`, clamped `[0, 1]`
- Bar color = `health_color(health_status(info))`
- Today marker = vertical line at fill position
- Window dropdown: `tk.StringVar` cycling `["30d", "60d", "90d"]`
- Health bar thickness: 6px (up from 4px on stat cards)

### 3.5 Activity Feed

Last 8 audit log entries, parsed from `_log_decrypt_all()`.

Event → dot color mapping:
| Event pattern | Dot color |
|--------------|-----------|
| `rotated` | `C["green"]` |
| `overdue` | `C["red"]` |
| `added` / `imported` | `C["accent"]` |
| `deleted` | `C["amber"]` |
| `unlocked` / `locked` | `C["text3"]` |
| default | `C["text3"]` |

`View all →` button calls `self._nav_switch("timeline")` and activates Activity sub-tab.

---

## 4. Timeline Tab

New sidebar nav entry: `("timeline", "Timeline")` — appended after `("cloud", "Cloud")`.

Frame: `self.timeline_frame` — created alongside other tab frames in `AppFrame.__init__`.

### 4.1 Sub-tab bar

Three `CTkButton` pills at top of frame: `Lifecycle`, `Activity`, `Forecast`.  
Active pill: `fg_color=C["accent_dim"]`, `text_color=C["accent"]`.  
Inactive: `fg_color="transparent"`, `text_color=C["text3"]`.  
State tracked in `tk.StringVar` `self._timeline_subtab`.

### 4.2 Lifecycle Sub-tab

Horizontal swim lanes, one row per key.

```
         [Created]──────[Rotated]────[Now]────[Due]
OPENAI   ├──────────────●────────────┼────────┤
STRIPE   ├─────────────────●──────────┼──┤
GITHUB   ├────────────────────────────┼─────────── (overdue marker)
```

- Full-width `tk.Canvas`, height = `max(len(keys) * 36 + 60, 400)`
- Wrapped in `CTkScrollableFrame` for overflow
- Key name column: 140px fixed left
- Timeline area: remaining width
- Time range: `min(created)` → `max(due or now + 30d)`
- Row colors: background alternates `C["bg"]` / `C["bg2"]`
- Rotation dot: filled circle `8px`, color = `health_color(status)`
- Click on row → `self.show_key_detail(name)`
- Redraws on `<Configure>` (window resize)

### 4.3 Activity Sub-tab

Full paginated audit log. 25 entries per page.

- Same row format as dashboard feed, full timestamp shown
- Pagination: `[← Prev]  Page 1 of N  [Next →]` at bottom
- Filter dropdown: All / Rotations / Imports / Logins
- `_timeline_page` and `_timeline_filter` as instance vars

### 4.4 Forecast Sub-tab

90-day calendar grid.

- Columns = days (today → today+90), grouped by month header
- Rows = keys with `rotation_schedule` set
- Cell colored if key rotation due that day: `C["amber"]` within 7 days, `C["red"]` if overdue
- Today column highlighted with `C["accent"]` header
- `tk.Canvas`-drawn, scrollable horizontally

---

## 5. Performance Fixes

### 5.1 Lazy Tab Rendering

Replace `render_all()` call in `_nav_switch` with dirty-flag pattern.

```python
# New instance vars in AppFrame.__init__:
self._tab_rendered: set[str] = set()
self._tab_dirty: set[str] = set()

def _nav_switch(self, key: str):
    # ... existing show/hide frame logic ...
    if key not in self._tab_rendered:
        getattr(self, f"render_{key}")()
        self._tab_rendered.add(key)
    elif key in self._tab_dirty:
        getattr(self, f"render_{key}")()
        self._tab_dirty.discard(key)

def _invalidate_tabs(self, *tabs: str):
    active = self._active_nav.get()
    for t in tabs:
        if t == active:
            getattr(self, f"render_{t}")()
        else:
            self._tab_dirty.add(t)
```

Replace all `self.render_all()` callsites with `self._invalidate_tabs("dashboard", "keys", ...)` — only invalidating tabs that actually changed.

Mutation → affected tabs:
| Mutation | Invalidate |
|----------|-----------|
| Key add/edit/delete/rotate | `dashboard`, `keys`, `timeline` |
| Project change | `projects`, `dashboard` |
| Cloud sync | `cloud`, `dashboard` |
| Security/MFA change | `security` |

### 5.2 Search Debounce

In `render_keys()`, replace the `trace_add` callback:

```python
self._search_debounce_id: str | None = None

def _on_search_change(self, *_):
    if self._search_debounce_id:
        self.after_cancel(self._search_debounce_id)
    self._search_debounce_id = self.after(200, self._render_key_rows)

# in render_keys():
self._search_var.trace_add("write", self._on_search_change)
```

### 5.3 Deferred Heavy Imports

Move `argon2`, `fido2`, `boto3`, `botocore` from module top to a post-login background thread.

```python
# At module top — remove these direct imports, replace with None sentinels:
argon2 = None
fido2 = None
boto3 = None

def _preload_heavy_modules():
    global argon2, boto3
    import argon2.low_level as _argon2; argon2 = _argon2
    try:
        import boto3 as _boto3; boto3 = _boto3
    except ImportError:
        pass
    try:
        import fido2 as _fido2; globals()["fido2"] = _fido2
    except ImportError:
        pass

# In LoginFrame.__init__:
import threading
threading.Thread(target=_preload_heavy_modules, daemon=True).start()
```

All callsites that use `argon2` / `boto3` / `fido2` already sit behind login, so they run after the thread completes.

---

## 5.4 Supporting Helpers (new)

**`_log_line_age_days(line: str) -> float`** — parses the `[YYYY-MM-DD HH:MM:SS]` prefix from a log line and returns days since that timestamp. Returns `float("inf")` on parse failure.

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

**Frame registration** — add to `AppFrame._NAV_FRAMES` dict (~line 2467):
```python
"timeline": "timeline_frame"
```

**Instance vars** — add to `AppFrame.__init__` alongside other state vars:
```python
self._timeline_subtab = tk.StringVar(value="lifecycle")
self._timeline_page = 0
self._timeline_filter = tk.StringVar(value="all")
```

---

## 6. File Change Summary

All changes in `pushkey.py`:

| Area | Change type | Approx lines |
|------|-------------|-------------|
| `C_DARK` / `C_LIGHT` | Replace | ~70 |
| `_draw_arc_gauge()` | New function | ~50 |
| `render_dashboard()` | Full rewrite | ~200 |
| `render_timeline()` | New function | ~200 |
| `_render_lifecycle()` | New function | ~80 |
| `_render_activity_tab()` | New function | ~60 |
| `_render_forecast_tab()` | New function | ~80 |
| `AppFrame.__init__` | Add timeline frame + dirty flags | ~20 |
| `_nav_switch()` | Lazy rendering logic | ~20 |
| `_invalidate_tabs()` | New method | ~15 |
| `render_keys()` | Debounce swap | ~10 |
| Module imports | Defer heavy libs | ~20 |
| **Total net new** | | **~825 lines** |

---

## 7. Out of Scope

- No changes to crypto layer, vault format, or cloud sync
- No new Python dependencies
- No changes to `server/`, `web/`, `vscode-pushkey/`, `browser-pushkey/`
- Light theme gets color updates only — no structural changes
