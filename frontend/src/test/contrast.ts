/**
 * WCAG contrast maths, for asserting colour pairs in a unit test.
 *
 * ─── Why this exists ────────────────────────────────────────────────────────
 * The project rule (.claude/rules/frontend.md) is a MANUAL two-theme browser
 * pass, and it has now failed twice in the same way: a `getComputedStyle` sweep
 * can only measure elements that are **in the DOM at that moment**. The
 * pantry-staples "Saved" notice renders only after a successful save, so a sweep
 * of the open settings modal reported "nothing below AA" while a 3.29:1 string
 * sat one interaction away. A snapshot of one state was reported as coverage of
 * all states.
 *
 * Asserting the DECLARED colour pairs closes that gap, because a constant does
 * not have to be on screen to be checked. It does not replace the browser pass
 * — only the browser knows what actually composites over what — but it catches
 * the case the browser pass structurally cannot see.
 *
 * jsdom computes no colours, so this deliberately takes plain hex strings and
 * does the arithmetic itself rather than going through getComputedStyle.
 *
 * ─── The second blind spot: colours with no declared surface ────────────────
 * The pairs above are all "explicit surface" cases — a component that sets a
 * background AND a colour, so both halves of the ratio are in one style object.
 * The other half of the codebase sets only a FOREGROUND and inherits whatever
 * it is rendered on. Those are exactly what shipped the MealPlanner dark-mode
 * bug: #4b5563 and #666666 are comfortable on white and 2.05:1 / 2.70:1 on the
 * `#242424` that index.css paints in dark mode.
 *
 * A blanket static scan of every foreground-only inline style cannot decide
 * those, because the surface is a property of the ANCESTOR, not the line: the
 * ~19 `#666` sites in this codebase are mostly inside modals and cards that pin
 * their own light background, where the colour is correct. Pairing every one of
 * them against both theme surfaces would fail all of them and the guard would be
 * turned off within a week.
 *
 * So the foreground-only cases that genuinely sit on the adaptive page
 * background are named as constants and checked against BOTH themes via
 * {@link THEME} — same trade as above: a constant does not have to be on screen,
 * or even on a known parent, to be checked.
 */

import type { ThemeName } from "../constants/theme";

/** `#rrggbb` → `[r, g, b]` (0-255). Throws on anything else, so a typo or an
 *  `rgba()`/named colour fails loudly instead of silently scoring as black. */
function rgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`contrast: expected #rrggbb, got ${JSON.stringify(hex)}`);
  const int = parseInt(m[1], 16);
  return [(int >> 16) & 255, (int >> 8) & 255, int & 255];
}

/** sRGB → relative luminance, per WCAG 2.x. */
function luminance(hex: string): number {
  const channels = rgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

/**
 * Composite `fg` at `alpha` over an opaque `bg`, returning the flattened hex.
 *
 * WCAG ratios are defined on opaque colours, so a translucent foreground —
 * `opacity: 0.75`, or index.css's own `rgba(255,255,255,0.87)` — has to be
 * flattened against what it sits on before it can be measured. Skipping this
 * step is how a semi-transparent colour gets "checked" at its nominal value and
 * scores far better than what the user actually sees.
 */
export function blend(fg: string, alpha: number, bg: string): string {
  const [f, b] = [rgb(fg), rgb(bg)];
  return (
    "#" +
    f
      .map((c, i) => Math.round(b[i] + (c - b[i]) * alpha))
      .map((c) => c.toString(16).padStart(2, "0"))
      .join("")
  );
}

/**
 * The two surfaces index.css actually paints, and the adaptive text colour each
 * one carries. `:root` is DARK by default and only flips light under
 * `@media (prefers-color-scheme: light)` — pinned against the stylesheet by
 * contrast.test.ts so these can't drift out of sync with it.
 */
export const THEME = {
  light: { bg: "#ffffff", fg: "#213547", fgAlpha: 1 },
  dark: { bg: "#242424", fg: "#ffffff", fgAlpha: 0.87 },
} as const satisfies Record<ThemeName, { bg: string; fg: string; fgAlpha: number }>;

/**
 * The colour that `color: "inherit"` resolves to on the page background, in the
 * given theme — optionally dimmed by an extra `opacity`.
 *
 * This is the theme-correct alternative to a hardcoded grey: it dims whatever
 * the adaptive default already is, so it cannot invert when the scheme flips.
 * The opacity still has to be checked, though — it is a real contrast lever.
 */
export function adaptiveText(scheme: ThemeName, opacity = 1): string {
  const t = THEME[scheme];
  return blend(t.fg, t.fgAlpha * opacity, t.bg);
}

/** Contrast ratio between two hex colours. Symmetric — role does not matter. */
export function contrastRatio(a: string, b: string): number {
  const [l1, l2] = [luminance(a), luminance(b)];
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

/**
 * The AA floor for text at `px` and `weight`.
 *
 * 3:1 applies only to LARGE text — 24px, or 18.66px when bold. Getting this
 * wrong in the lenient direction is how a failing colour passes a check, so the
 * threshold is derived rather than assumed.
 */
export function wcagAAFloor(px: number, weight = 400): 3 | 4.5 {
  return px >= 24 || (px >= 18.66 && weight >= 700) ? 3 : 4.5;
}

/** Assertion-friendly: `{ ratio, floor, passes }` for a text colour on a surface. */
export function checkText(
  fg: string,
  bg: string,
  px: number,
  weight = 400,
): { ratio: number; floor: number; passes: boolean } {
  const ratio = Math.round(contrastRatio(fg, bg) * 100) / 100;
  const floor = wcagAAFloor(px, weight);
  return { ratio, floor, passes: ratio >= floor };
}
