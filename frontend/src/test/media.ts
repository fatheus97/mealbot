/**
 * The `window.matchMedia` mock, shared by every JS-driven media hook.
 *
 * Deliberately dependency-free and separate from test-utils.tsx: setup.ts has to
 * reset this between tests, and setup.ts must not pull the React/app module
 * graph in as a side effect — its `vi.stubGlobal('localStorage', …)` runs AFTER
 * imports are evaluated, so anything imported there that touches storage at
 * module scope (zustand's persist middleware, for one) captures `undefined`.
 *
 * Two independent axes — viewport (`useIsMobile`) and colour scheme
 * (`usePrefersDark`) — answer from ONE mock, because `window.matchMedia` is a
 * single global: two setters that each installed their own stub would clobber
 * each other, so `setMobileViewport(true)` after `setColorScheme('dark')` would
 * silently drop the theme.
 */
const media = { isMobile: false, isDark: false };

function install() {
  window.matchMedia = ((query: string) => ({
    matches: /max-width/.test(query)
      ? media.isMobile
      : /prefers-color-scheme:\s*dark/.test(query)
        ? media.isDark
        : /prefers-color-scheme:\s*light/.test(query)
          ? !media.isDark
          : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

/**
 * Install a `matchMedia` mock so `useIsMobile()` reports the given viewport in
 * tests. jsdom ships no `matchMedia`, so without this every test renders the
 * desktop branch — call this before rendering to exercise the mobile branch.
 * Cleared automatically after each test (see src/test/setup.ts).
 */
export function setMobileViewport(isMobile: boolean) {
  media.isMobile = isMobile;
  install();
}

/**
 * Install a `matchMedia` mock so `usePrefersDark()` reports the given OS colour
 * scheme. Same deal as `setMobileViewport`: with no mock, jsdom renders the
 * light branch, so call this before rendering to exercise dark mode.
 */
export function setColorScheme(scheme: "light" | "dark") {
  media.isDark = scheme === "dark";
  install();
}

/** Drop both axes back to their defaults. Called from the global `afterEach`,
 *  so a dark-mode or mobile test cannot leak into the next one. */
export function __resetMediaForTests() {
  media.isMobile = false;
  media.isDark = false;
}
