import { DEFAULT_LOCALE, type Locale } from "../store/useLocaleStore";

/**
 * Output that depends on the chosen UI locale but is NOT a dictionary string:
 * a formatted date, and the path of a translated static page.
 *
 * Both were getting derived from something other than the app locale, which is
 * invisible while the two agree and wrong the moment they don't — the exact
 * shape of bug the dictionary's compiler-enforced completeness cannot catch,
 * because there is no key to be missing.
 */

/**
 * Locale tags to hand to `Intl`, most preferred first.
 *
 * `toLocaleDateString(undefined, …)` resolves to the BROWSER locale, so a
 * Czech UI on an English browser rendered "Aug 7, 2026" next to Czech copy.
 * Passing the bare app locale fixes the language but throws away the user's
 * regional conventions, and en-GB reading "Aug 7" instead of "7 Aug" is a
 * second, quieter regression.
 *
 * So: keep every browser tag whose PRIMARY SUBTAG matches the app locale
 * (en-GB survives under `en`, cs-CZ under `cs`), then fall back to the bare
 * locale. The app decides the language; the browser still decides the region.
 */
export function localeTags(
  locale: Locale,
  languages: readonly string[] = typeof navigator === "undefined"
    ? []
    : (navigator.languages ?? []),
): string[] {
  const regional = languages.filter(
    (tag) => tag.toLowerCase().split("-")[0] === locale,
  );
  return [...regional, locale];
}

/** A medium-length date in the user's language, or "" for a null/invalid input. */
export function formatDate(iso: string | null, locale: Locale): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(localeTags(locale), {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Locales that actually HAVE translated legal pages built and served.
 *
 * An allowlist rather than `locale !== DEFAULT_LOCALE`, so adding a UI locale
 * cannot silently start linking to a 404. `vite.config.ts` decides what exists
 * (`cs/privacy.html`, `cs/terms.html` today); this list has to be extended by
 * hand alongside it, and `localeFormat.test.ts` reads that config and fails if
 * the two disagree in EITHER direction.
 */
const LOCALES_WITH_LEGAL_PAGES: readonly Locale[] = ["cs"];

/**
 * Path of a legal document in the user's language.
 *
 * The paywall linked at `/terms` and `/privacy` unconditionally, so a Czech
 * user one click from paying was sent to the English contract — the two
 * documents that #396 made equally authoritative, with the Czech one the
 * version that actually binds a Czech consumer.
 */
export function legalHref(locale: Locale, doc: "terms" | "privacy"): string {
  return LOCALES_WITH_LEGAL_PAGES.includes(locale) && locale !== DEFAULT_LOCALE
    ? `/${locale}/${doc}`
    : `/${doc}`;
}
