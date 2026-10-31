// Honours a language the visitor CHOSE, on the six static pages.
//
// Choosing from the browser's languages is nginx's job ($lang_to_czech in
// nginx.conf): an HTTP redirect keeps the visitor's original Referer, which a
// script navigation loses. nginx cannot see a choice, though. It lives in
// localStorage, and the site sets no cookie for it, because the privacy policy
// promises no cookies to anyone who never signs in. So this script:
//
// - records a click on a language link (a[hreflang]) as an explicit choice, in
//   the record the app's locale store persists (src/store/useLocaleStore.ts),
//   so one choice holds here and in the app;
// - on a page in the other language, swaps to the chosen language's version,
//   keeping the query string and anchor.
//
// Loaded render-blocking from <head> (the CSP forbids inline scripts), so the
// swap happens before the wrong page paints. No loop: on a page already in the
// chosen language it does nothing, and nginx never redirects a visitor coming
// from this site. src/test/langRedirect.test.ts runs this file against the store.
(() => {
  const STORE_KEY = "mealbot-locale";
  const LOCALES = ["en", "cs"];
  const COUNTERPART = {
    "/": "/cs",
    "/cs": "/",
    "/privacy": "/cs/privacy",
    "/cs/privacy": "/privacy",
    "/terms": "/cs/terms",
    "/cs/terms": "/terms",
  };

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
      // Storage blocked: nginx still never bounces a visitor moving within the site.
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
  const counterpart = COUNTERPART[path];
  const pageLocale = /^\/cs(\/|$)/.test(path) ? "cs" : "en";
  const choice = savedChoice();
  if (counterpart && choice && choice !== pageLocale) {
    location.replace(counterpart + location.search + location.hash);
  }
})();
