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
//   so one choice holds here and in the app, and carries the query string over;
// - on a page in the other language, swaps to the chosen language's version,
//   keeping the query string and anchor, and adding ?lang=<choice>.
//
// That marker is what makes it loop-proof. nginx never redirects a request
// carrying ?lang= (nor one coming from this site, but some browsers send no
// Referer at all), and on a page already in the chosen language this script
// does nothing. On arrival the marker is stripped from the address bar.
//
// Loaded render-blocking from <head> (the CSP forbids inline scripts), so the
// swap happens before the wrong page paints. src/test/langRedirect.test.ts runs
// this file against the store.
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
      if (!isLocale(locale)) return;
      remember(locale);
      // Switching language must not drop the campaign tags (utm_source and the
      // rest). Done at click time so the href crawlers see stays the clean URL
      // the hreflang tags name.
      const href = link.getAttribute("href");
      if (location.search && href && !href.includes("?")) link.setAttribute("href", href + location.search);
    },
    true,
  );

  const path = location.pathname.replace(/\.html$/, "").replace(/\/index$/, "/").replace(/(.)\/$/, "$1");
  const counterpart = COUNTERPART[path];
  const pageLocale = /^\/cs(\/|$)/.test(path) ? "cs" : "en";
  const choice = savedChoice();
  const params = new URLSearchParams(location.search);
  const marked = params.has("lang");
  params.delete("lang");
  if (counterpart && choice && choice !== pageLocale) {
    params.set("lang", choice);
    location.replace(`${counterpart}?${params}${location.hash}`);
  } else if (marked) {
    // Not for bookmarks or sharing: the marker only has to reach nginx once.
    const query = params.toString();
    history.replaceState(history.state, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
  }
})();
