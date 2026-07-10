import { useSyncExternalStore } from "react";

/**
 * Shared responsive breakpoints (px). The app is styled with inline `style={}`
 * objects, which win over any stylesheet on specificity — so CSS `@media`
 * queries can't make those components responsive. Responsiveness is therefore
 * JS-driven: components read `useIsMobile()` and branch their style objects.
 */
export const BREAKPOINTS = {
  /** At or below this width we treat the viewport as a phone. */
  mobile: 640,
} as const;

const MOBILE_QUERY = `(max-width: ${BREAKPOINTS.mobile}px)`;

// Module-level (stable) store callbacks so useSyncExternalStore doesn't
// re-subscribe on every render.
function subscribe(callback: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mql = window.matchMedia(MOBILE_QUERY);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getSnapshot(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(MOBILE_QUERY).matches;
}

// SSR / no-`window` default: assume desktop so the server and first client
// render agree (avoids a hydration mismatch); the real value lands on mount.
function getServerSnapshot(): boolean {
  return false;
}

/**
 * `true` when the viewport is phone-sized (<= {@link BREAKPOINTS.mobile}px).
 * Re-renders the consumer on viewport crossings (rotation, resize, devtools).
 */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
