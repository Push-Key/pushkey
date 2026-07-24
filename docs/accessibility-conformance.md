# Pushkey Local Web App Accessibility Conformance Record

Status date: 2026-07-24
Target: WCAG 2.2 Level AA
Scope: the local web app (`web-app/`) critical journeys

This record backs the roadmap item "Meet WCAG 2.2 AA for critical journeys" in
`docs/PRODUCTION_READINESS_PLAN.md`. It states what was tested, how, what was
found and fixed, and — deliberately — what an automated scan cannot establish.

## Scope: Critical Journeys

A journey is "critical" if a user cannot use the product without completing it.
Nine are covered:

| Journey | Entry point |
|---|---|
| Locked vault / unlock with master password | locked shell |
| Locked vault / unlock with recovery code | locked shell, Recovery Code mode |
| Dashboard | unlocked shell |
| Vault list | Vault tab |
| Add key form | Vault tab, Add key disclosure |
| Health | Health tab |
| Projects | Projects tab |
| Settings | Settings tab |
| Sidebar count badges | unlocked shell with stale keys and overdue rotations |

The badge journey exists because those two badges only render when their counts
are non-zero, so no other journey reaches them.

## Method

Two complementary layers, both automated and both run in CI:

1. **Machine scan** — `web-app/tests/e2e/wcag.spec.ts` runs axe-core
   (`@axe-core/playwright`) over each journey with the rule tags
   `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`, and fails on any
   violation. Run on Chromium, Firefox, and WebKit.
2. **Authored-semantics assertions** — `web-app/tests/e2e/accessibility.spec.ts`
   and `tests/test_web_app_accessibility_static.py` assert the things a scanner
   cannot infer intent for: every interactive control has an accessible name,
   disclosure controls expose `aria-expanded`/`aria-controls`, the active tab
   exposes `aria-current`, status and error text lands in `role="status"` /
   `role="alert"` live regions, the skip link targets `#main-content`, and
   filled status surfaces use the AA-contrast color tokens.

Reproduce:

```powershell
npm --prefix web-app run test:e2e -- wcag.spec.ts accessibility.spec.ts
.\.venv\Scripts\python.exe -m pytest tests\test_web_app_accessibility_static.py -q
```

## Result

All nine journeys pass the WCAG 2.0/2.1/2.2 A + AA axe rule set with zero
violations on Chromium, Firefox, and WebKit.

## Defects Found And Fixed

The first scan failed on all journeys. Four distinct defects, all now fixed and
all now regression-guarded by the tests above:

| Defect | Criterion | Fix |
|---|---|---|
| Toast viewport was a `div` carrying `aria-label="Notifications"` with no role; `aria-label` is prohibited on a generic element | 4.1.2 Name, Role, Value (A) | Added `role="region"` to the live-region container in `web-app/src/lib/toast.tsx`. `aria-atomic="false"` queueing behaviour is unchanged. |
| Sidebar footer meta (`v0.1.0`, Settings link) rendered at `--color-muted-foreground/70` = `#656d75` on `#0d1117`, contrast 3.6:1 | 1.4.3 Contrast (Minimum) (AA) | Removed the `/70` dim in `web-app/src/components/sidebar.tsx`. Undimmed is 6.15:1. |
| Destructive button used `#ef4444` as a background behind `#e6edf3`, contrast 3.18:1 | 1.4.3 Contrast (Minimum) (AA) | Added `--color-destructive-strong: #b91c1c` (5.48:1) and used it for the filled button variant. `--color-destructive` is unchanged because it is also used as *foreground* text on the dark background, where it already passes at 5.14:1. |
| Sidebar count badges used `#ef4444` (3.76:1) and Tailwind `orange-500` (2.8:1) behind white text at 10px semibold | 1.4.3 Contrast (Minimum) (AA) | Filled badges now use `--color-destructive-strong` (6.47:1 on white) and `--color-warning-strong: #b45309` (5.02:1 on white). |

## Limits Of This Record

axe-core evaluates roughly a third of the WCAG success criteria. A clean scan is
necessary but not sufficient for a conformance claim, so the criteria below are
stated with what evidence does and does not exist.

Addressed with test evidence, not merely asserted:

- **1.3.1 Info and Relationships** — landmark roles, `role="region"` panels,
  `aria-controls`/`aria-expanded` pairs asserted in `accessibility.spec.ts`.
- **2.4.1 Bypass Blocks** — skip link to `#main-content`, asserted in both the
  E2E and static suites.
- **2.4.3 Focus Order / 2.4.7 Focus Visible** — a global
  `focus-visible:ring-[var(--color-ring)]` treatment on interactive variants;
  the skip link's `focus:not-sr-only` reveal is asserted.
- **4.1.2 Name, Role, Value** — every visible interactive control is checked for
  a non-empty accessible name on each journey by
  `collectUnnamedInteractiveControls`.
- **1.4.3 Contrast (Minimum)** — axe-verified per journey, plus static token
  assertions so a future dim or fill change fails a unit test.

Not machine-checkable and **not yet independently audited**. These remain open
for the manual accessibility review, and no conformance claim is made for them
here:

- **1.4.10 Reflow** and **1.4.12 Text Spacing** — responsive structure is
  asserted statically (`flex-col md:flex-row`, `w-full md:w-56`) but no
  400%-zoom or text-spacing override review has been performed.
- **2.1.1 Keyboard** / **2.1.2 No Keyboard Trap** — the app authors no custom
  keyboard handlers or focus traps outside Radix primitives, but no manual
  keyboard-only walkthrough of each journey has been recorded.
- **2.4.11 Focus Not Obscured (Minimum)** (new in 2.2) — the fixed toast
  viewport sits bottom-right and could overlap a focused control at small
  viewports. Not yet reviewed.
- **2.5.7 Dragging Movements** and **2.5.8 Target Size (Minimum)** (new in 2.2)
  — no drag interactions exist, but the 16px-tall count badges and icon-only
  vault row actions have not been measured against the 24×24 CSS px minimum.
- **3.3.7 Redundant Entry** and **3.3.8 Accessible Authentication (Minimum)**
  (new in 2.2) — the unlock flow accepts paste into the master-password field,
  which satisfies 3.3.8, but this has not been formally reviewed.
- **1.2.x** media alternatives — not applicable; the app ships no audio or
  video.
- **2.4.5 Multiple Ways** — not applicable to a single-window local app with one
  navigation mechanism.

## Follow-Up

- Commission the manual review covering the "not yet independently audited"
  criteria above. That is an external gate, tracked alongside the independent
  security review in `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`.
- The public marketing/admin surfaces in `web/` are out of scope for this
  record. They have their own coverage and are not part of the local app's
  critical journeys.
