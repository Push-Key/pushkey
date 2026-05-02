"""Lucide-inspired stroke icons drawn via PIL.

No external assets, no SVG dep. Every icon is a function that returns a
transparent PIL.Image at requested size and stroke color. Scales crisply
because we redraw at each requested size rather than upscaling pixels.

Usage:
    from pushkey_icons import load_icon
    img = load_icon("key", size=20, color="#22D3EE")
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(20, 20))
"""
from __future__ import annotations
from PIL import Image, ImageDraw
from typing import Callable
import math

# ── helpers ─────────────────────────────────────────────────────────────

def _canvas(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _hex(color: str) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    if len(c) == 6:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)
    if len(c) == 8:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16))
    return (255, 255, 255, 255)


def _stroke(size: int) -> int:
    # Lucide uses 2px stroke at 24px viewport; scale proportionally.
    return max(1, round(size / 12))


# ── icon drawers (Lucide-inspired, 24×24 design grid) ───────────────────

def _key(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # head circle + horizontal shaft + 2 teeth
    cx, cy = s * 0.32, s * 0.68
    r = s * 0.18
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=w)
    # shaft from head to right edge
    d.line([cx + r, cy, s * 0.92, cy], fill=c, width=w)
    # tip notches
    d.line([s * 0.92, cy, s * 0.92, cy - s * 0.13], fill=c, width=w)
    d.line([s * 0.78, cy, s * 0.78, cy - s * 0.10], fill=c, width=w)


def _lock(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # shackle arc
    d.arc([s * 0.27, s * 0.10, s * 0.73, s * 0.55],
          start=180, end=360, fill=c, width=w)
    # body
    d.rounded_rectangle([s * 0.20, s * 0.45, s * 0.80, s * 0.88],
                        radius=s * 0.06, outline=c, width=w)


def _shield(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    pts = [
        (s * 0.50, s * 0.10),
        (s * 0.86, s * 0.22),
        (s * 0.86, s * 0.55),
        (s * 0.50, s * 0.92),
        (s * 0.14, s * 0.55),
        (s * 0.14, s * 0.22),
    ]
    d.line(pts + [pts[0]], fill=c, width=w, joint="curve")


def _plus(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    d.line([s * 0.50, s * 0.18, s * 0.50, s * 0.82], fill=c, width=w)
    d.line([s * 0.18, s * 0.50, s * 0.82, s * 0.50], fill=c, width=w)


def _search(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # circle + diagonal handle
    cx, cy = s * 0.43, s * 0.43
    r = s * 0.27
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=w)
    d.line([cx + r * 0.71, cy + r * 0.71, s * 0.85, s * 0.85], fill=c, width=w)


def _copy(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # two overlapping rounded rects
    d.rounded_rectangle([s * 0.32, s * 0.32, s * 0.86, s * 0.86],
                        radius=s * 0.07, outline=c, width=w)
    d.rounded_rectangle([s * 0.14, s * 0.14, s * 0.68, s * 0.68],
                        radius=s * 0.07, outline=c, width=w)


def _pencil(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # diagonal pencil body
    pts = [
        (s * 0.65, s * 0.12),
        (s * 0.88, s * 0.35),
        (s * 0.30, s * 0.93),
        (s * 0.10, s * 0.93),
        (s * 0.10, s * 0.73),
    ]
    d.line(pts + [pts[0]], fill=c, width=w, joint="curve")
    # tip line
    d.line([(s * 0.50, s * 0.27), (s * 0.73, s * 0.50)], fill=c, width=w)


def _trash(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # lid
    d.line([s * 0.12, s * 0.27, s * 0.88, s * 0.27], fill=c, width=w)
    # handle
    d.line([s * 0.36, s * 0.16, s * 0.64, s * 0.16], fill=c, width=w)
    d.line([s * 0.36, s * 0.16, s * 0.36, s * 0.27], fill=c, width=w)
    d.line([s * 0.64, s * 0.16, s * 0.64, s * 0.27], fill=c, width=w)
    # body
    pts = [(s * 0.22, s * 0.27), (s * 0.78, s * 0.27),
           (s * 0.72, s * 0.90), (s * 0.28, s * 0.90)]
    d.line(pts + [pts[0]], fill=c, width=w, joint="curve")
    # inner lines
    d.line([s * 0.40, s * 0.40, s * 0.40, s * 0.78], fill=c, width=w)
    d.line([s * 0.60, s * 0.40, s * 0.60, s * 0.78], fill=c, width=w)


def _eye(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # almond outline (two arcs forming lens)
    cx, cy = s * 0.50, s * 0.50
    # outer almond via Bezier-ish: use two arcs
    d.arc([s * 0.05, s * 0.20, s * 0.95, s * 0.80],
          start=10, end=170, fill=c, width=w)
    d.arc([s * 0.05, s * 0.20, s * 0.95, s * 0.80],
          start=190, end=350, fill=c, width=w)
    # pupil
    r = s * 0.15
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=w)


def _refresh(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # 270° arc + arrow head
    cx, cy = s * 0.50, s * 0.50
    bbox = [s * 0.18, s * 0.18, s * 0.82, s * 0.82]
    d.arc(bbox, start=45, end=315, fill=c, width=w)
    # arrowhead at top-right
    ah = s * 0.10
    tip = (s * 0.82, s * 0.32)
    d.line([tip, (tip[0] - ah, tip[1] - ah * 0.2)], fill=c, width=w)
    d.line([tip, (tip[0] - ah * 0.2, tip[1] + ah)], fill=c, width=w)


def _gear(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    cx, cy = s * 0.50, s * 0.50
    r_outer = s * 0.40
    r_inner = s * 0.30
    teeth = 8
    # draw spokes as short radial lines (simplified gear)
    for i in range(teeth):
        a = (i / teeth) * 2 * math.pi
        x1 = cx + r_inner * math.cos(a)
        y1 = cy + r_inner * math.sin(a)
        x2 = cx + r_outer * math.cos(a)
        y2 = cy + r_outer * math.sin(a)
        d.line([x1, y1, x2, y2], fill=c, width=w + 1)
    # central ring
    d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
              outline=c, width=w)
    # hub
    rh = s * 0.10
    d.ellipse([cx - rh, cy - rh, cx + rh, cy + rh], outline=c, width=w)


def _chevron_down(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    pts = [(s * 0.22, s * 0.38), (s * 0.50, s * 0.66), (s * 0.78, s * 0.38)]
    d.line(pts, fill=c, width=w, joint="curve")


def _chevron_right(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    pts = [(s * 0.38, s * 0.22), (s * 0.66, s * 0.50), (s * 0.38, s * 0.78)]
    d.line(pts, fill=c, width=w, joint="curve")


def _check(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    d.line([(s * 0.18, s * 0.52), (s * 0.42, s * 0.74), (s * 0.84, s * 0.28)],
           fill=c, width=w, joint="curve")


def _x(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    d.line([(s * 0.22, s * 0.22), (s * 0.78, s * 0.78)], fill=c, width=w)
    d.line([(s * 0.78, s * 0.22), (s * 0.22, s * 0.78)], fill=c, width=w)


def _folder(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # tab + body
    d.line([s * 0.10, s * 0.30, s * 0.40, s * 0.30,
            s * 0.50, s * 0.42, s * 0.90, s * 0.42], fill=c, width=w, joint="curve")
    d.rounded_rectangle([s * 0.10, s * 0.30, s * 0.90, s * 0.85],
                        radius=s * 0.06, outline=c, width=w)


def _activity(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # ECG-style line
    pts = [(s * 0.10, s * 0.50), (s * 0.30, s * 0.50),
           (s * 0.40, s * 0.20), (s * 0.55, s * 0.80),
           (s * 0.65, s * 0.50), (s * 0.90, s * 0.50)]
    d.line(pts, fill=c, width=w, joint="curve")


def _bell(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # bell body (inverted U with flared base) + clapper
    pts = [(s * 0.25, s * 0.72), (s * 0.30, s * 0.40),
           (s * 0.50, s * 0.20), (s * 0.70, s * 0.40),
           (s * 0.75, s * 0.72)]
    d.line(pts + [(s * 0.25, s * 0.72)], fill=c, width=w, joint="curve")
    d.line([s * 0.45, s * 0.85, s * 0.55, s * 0.85], fill=c, width=w)


def _user(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # head + shoulders
    cx = s * 0.50
    rh = s * 0.18
    d.ellipse([cx - rh, s * 0.20, cx + rh, s * 0.56], outline=c, width=w)
    d.arc([s * 0.18, s * 0.55, s * 0.82, s * 1.05],
          start=180, end=360, fill=c, width=w)


def _bar_chart(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    # 3 vertical bars of varying height
    y_base = s * 0.85
    bw = s * 0.14
    for x_center, height in [(s * 0.25, 0.50), (s * 0.50, 0.30), (s * 0.75, 0.65)]:
        d.rectangle([x_center - bw/2, y_base - s * height,
                     x_center + bw/2, y_base], outline=c, width=w)


def _clock(d: ImageDraw.ImageDraw, s: int, c: tuple, w: int) -> None:
    cx, cy = s * 0.50, s * 0.50
    r = s * 0.36
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=w)
    d.line([cx, cy, cx, cy - r * 0.65], fill=c, width=w)  # hour hand
    d.line([cx, cy, cx + r * 0.5, cy], fill=c, width=w)   # minute hand


# ── registry ────────────────────────────────────────────────────────────

_DRAWERS: dict[str, Callable] = {
    "key":           _key,
    "lock":          _lock,
    "shield":        _shield,
    "plus":          _plus,
    "search":        _search,
    "copy":          _copy,
    "pencil":        _pencil,
    "edit":          _pencil,  # alias
    "trash":         _trash,
    "delete":        _trash,   # alias
    "eye":           _eye,
    "refresh":       _refresh,
    "rotate":        _refresh, # alias
    "gear":          _gear,
    "settings":      _gear,    # alias
    "chevron-down":  _chevron_down,
    "chevron-right": _chevron_right,
    "check":         _check,
    "x":             _x,
    "close":         _x,       # alias
    "folder":        _folder,
    "activity":      _activity,
    "bell":          _bell,
    "user":          _user,
    "bar-chart":     _bar_chart,
    "dashboard":     _bar_chart, # alias
    "clock":         _clock,
}


# ── cache + public API ──────────────────────────────────────────────────

_CACHE: dict[tuple[str, int, str], Image.Image] = {}


def load_icon(name: str, size: int = 20, color: str = "#FFFFFF") -> Image.Image:
    """Render and cache a Lucide-style icon as a PIL Image (transparent bg)."""
    key = (name, size, color.upper())
    if key in _CACHE:
        return _CACHE[key]
    drawer = _DRAWERS.get(name)
    if drawer is None:
        # fallback: empty transparent square
        img, _ = _canvas(size)
        _CACHE[key] = img
        return img
    img, d = _canvas(size)
    drawer(d, size, _hex(color), _stroke(size))
    _CACHE[key] = img
    return img


def available_icons() -> list[str]:
    return sorted(_DRAWERS.keys())


if __name__ == "__main__":
    # smoke test — render every icon to a contact sheet
    import os
    out = "_icons_preview.png"
    icons = available_icons()
    cols = 6
    rows = (len(icons) + cols - 1) // cols
    cell = 60
    sheet = Image.new("RGBA", (cols * cell, rows * cell), (10, 22, 40, 255))
    for i, name in enumerate(icons):
        r, c = divmod(i, cols)
        ico = load_icon(name, size=40, color="#22D3EE")
        sheet.paste(ico, (c * cell + 10, r * cell + 10), ico)
    sheet.save(out)
    print(f"Wrote {out} with {len(icons)} icons")
