// Language routing for the static pages: a visitor whose browser prefers Czech
// (or Slovak) is sent from an English page to its Czech counterpart, and a
// language picked on the page's own language link is remembered.
//
// Loaded render-blocking from <head>: the CSP forbids inline scripts, and the
// landing's deferred module would only redirect after the English page painted.
// It runs on the English landing, privacy and terms pages (redirect + link) and
// on the Czech landing (link only). Czech pages never redirect, so no loop.
//
// It mirrors detectLocale() in src/store/useLocaleStore.ts and reads and writes
// that store's persisted record, so one choice holds here and in the app.
// src/test/langRedirect.test.ts runs this file against both.
(() => {
  const STORE_KEY = "mealbot-locale";
  const LOCALES = ["en", "cs"];
  // Slovak readers get Czech rather than English.
  const ALIASES = { sk: "cs" };
  const CZECH_PAGE = { "/": "/cs", "/privacy": "/cs/privacy", "/terms": "/cs/terms" };

  const isLocale = (value) => LOCALES.includes(value);

  function savedChoice() {
    try {
      const state = JSON.parse(localStorage.getItem(STORE_KEY) ?? "null")?.state;
      return state?.explicit === true && isLocale(state.locale) ? state.locale : null;
    } catch {
      return null; // storage blocked, or a record we cannot read
    }
  }

  function remember(locale) {
    try {
      localStorage.setItem(
        STORE_KEY,
        JSON.stringify({ state: { locale, explicit: true }, version: 1 }),
      );
    } catch {
      // Storage blocked: the referrer check below still stops a bounce-back.
    }
  }

  function detect(languages) {
    for (const tag of languages) {
      if (typeof tag !== "string") continue;
      const primary = tag.toLowerCase().split("-")[0];
      const locale = ALIASES[primary] ?? primary;
      if (isLocale(locale)) return locale;
    }
    return "en";
  }

  // Arriving from one of our Czech pages means the visitor chose English.
  function cameFromCzechPage() {
    try {
      const from = new URL(document.referrer);
      return from.origin === location.origin && /^\/cs(\/|$)/.test(from.pathname);
    } catch {
      return false;
    }
  }

  document.addEventListener(
    "click",
    (event) => {
      const link = event.target instanceof Element ? event.target.closest("a[hreflang]") : null;
      const locale = link?.getAttribute("hreflang");
      if (isLocale(locale)) remember(locale);
    },
    true,
  );

  const path = location.pathname.replace(/\.html$/, "").replace(/\/index$/, "/").replace(/(.)\/$/, "$1");
  const czech = CZECH_PAGE[path];
  if (!czech || cameFromCzechPage()) return;
  const locale = savedChoice() ?? detect(navigator.languages ?? [navigator.language]);
  if (locale === "cs") location.replace(czech + location.search + location.hash);
})();
