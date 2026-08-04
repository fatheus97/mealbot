import { useSyncExternalStore } from "react";

/**
 * The OS colour-scheme equivalent of {@link import("./useIsMobile").useIsMobile}
 * — and it exists for the same reason.
 *
 * The app is 100% inline `style={}`, which beats any stylesheet on specificity,
 * so a CSS `@media (prefers-color-scheme: dark)` block cannot reach a hardcoded
 * colour in a style object. Most of the time that is fine: text with no explicit
 * `color` inherits the adaptive default from `index.css` and stays legible in
 * both themes. It stops being fine when a colour genuinely has to differ per
 * theme — an accent blue readable on white (#2563eb, 5.17:1) drops to 3.00:1 on
 * the dark `#242424` page background, and the lighter blue that fixes dark mode
 * fails on white. No single hex satisfies both, so the branch has to happen in
 * JS.
 *
 * Reach for this ONLY for that case. A muted grey does not need it — prefer
 * `color: "inherit"` plus an `opacity`, which is theme-correct by construction
 * because it dims whatever the adaptive default already is.
 */
const DARK_QUERY = "(prefers-color-scheme: dark)";

// Module-level (stable) store callbacks so useSyncExternalStore doesn't
// re-subscribe on every render.
function subscribe(callback: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mql = window.matchMedia(DARK_QUERY);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getSnapshot(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(DARK_QUERY).matches;
}

// SSR / no-`window` default: light. Note this does NOT match index.css, whose
// `:root` is dark and only flips light under `@media (prefers-color-scheme:
// light)` — so a hypothetical matchMedia-less browser would render the dark
// background with the light-theme accents. No such browser exists (matchMedia is
// universally supported); the only consumers of this branch are jsdom and SSR,
// where nothing is painted. Light keeps it consistent with `useIsMobile`'s
// "assume desktop" default and with the test-utils matchMedia mock.
function getServerSnapshot(): boolean {
  return false;
}

/**
 * `true` when the OS/browser asks for a dark colour scheme. Re-renders the
 * consumer when the user flips their system theme mid-session.
 */
export function usePrefersDark(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
