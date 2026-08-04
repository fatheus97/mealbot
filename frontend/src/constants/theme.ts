import type { CSSProperties } from "react";

/**
 * Text colours for content that sits on the ADAPTIVE PAGE BACKGROUND.
 *
 * index.css is dark-by-default (`:root { background-color: #242424 }`) and only
 * flips light under `@media (prefers-color-scheme: light)`. Anything painted
 * straight onto that — as opposed to onto a card/modal that pins its own
 * surface — is therefore on a background that changes with the OS theme, while
 * an inline `style={}` colour does not. That mismatch is the app's most-repeated
 * bug (see .claude/rules/frontend.md).
 *
 * Most of the time the fix is to NOT set a colour, or to use
 * {@link MUTED_PAGE_TEXT}. These entries are the residue: colours that carry
 * meaning (an accent, an error) and where no single hex clears WCAG AA on both
 * surfaces — #2563eb is 5.17:1 on white but 3.00:1 on #242424, and the lighter
 * blue that fixes dark mode falls to 2.54:1 on white. Pick with
 * `usePrefersDark()`; the ratios are pinned in src/test/contrast.test.ts.
 */
export type ThemeName = "light" | "dark";

export const PAGE_TEXT = {
  /** Selected mode tab (and its underline). */
  tabActive: { light: "#2563eb", dark: "#60a5fa" }, // 5.17:1 / 6.11:1
  /** Unselected mode tab — deliberately quieter than the body text. */
  tabInactive: { light: "#4b5563", dark: "#9ca3af" }, // 7.56:1 / 6.11:1
  /** Inline failure text + its border. */
  error: { light: "#b91c1c", dark: "#f87171" }, // 6.47:1 / 5.61:1
} as const satisfies Record<string, Record<ThemeName, string>>;

/**
 * Muted/secondary text on the adaptive page background.
 *
 * `inherit` + `opacity` instead of a grey, because it dims whatever the adaptive
 * default already is and so cannot invert when the scheme flips — no hook and no
 * per-theme constant needed. (DietarySelector's disclaimer already does this.)
 * The opacity is still a real contrast lever: 0.75 lands at 5.73:1 on white and
 * 7.40:1 on #242424, both above the 4.5:1 AA floor. Don't lower it without
 * re-running src/test/contrast.test.ts.
 *
 * Only for the page background. Text on an explicit light surface (a modal, a
 * card) should keep using a fixed grey like #666 — that surface doesn't move.
 */
export const MUTED_PAGE_OPACITY = 0.75;

export const MUTED_PAGE_TEXT: CSSProperties = {
  color: "inherit",
  opacity: MUTED_PAGE_OPACITY,
};
