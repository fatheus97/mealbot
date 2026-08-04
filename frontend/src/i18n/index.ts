import { useMemo } from "react";
import { useLocaleStore, type Locale, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { en } from "./en";
import { cs } from "./cs";

/**
 * Hand-rolled i18n. ~80 lines, zero dependencies, no provider, no build step.
 *
 * ─── Why not react-i18next / lingui / typesafe-i18n ────────────────────────
 * The two genuinely hard parts of translation are plural selection and
 * locale-correct formatting, and the PLATFORM already does both:
 * `Intl.PluralRules` knows that Czech has one/few/many/other and that 2–4 take
 * "few", and `Intl.DateTimeFormat` / `Number.toLocaleString` handle the rest.
 * What a library would add on top is interpolation (a regex) and a React
 * binding — against ~50 KB of bundle, an ICU parser, and a `<I18nextProvider>`.
 *
 * That provider is the decisive cost here, not the bundle: 41 of the 50
 * frontend test files call RTL's plain `render` rather than the shared
 * `renderWithProviders`, so a context-based library means editing 41 test files
 * before translating a single string. Reading the locale from the zustand store
 * — the pattern this app already uses in `store/usePreferencesStore.ts` —
 * needs no provider, so every existing test keeps working untouched.
 *
 * Upgrade path if this is ever outgrown (nested selects, gender, ordinals):
 * `@messageformat/core` slots in behind `t()` without changing a call site.
 */

export type TranslationKey = keyof typeof en;

/**
 * Base keys of plural sets — `"time.minutes_other"` contributes `"time.minutes"`.
 * `tn()` accepts only these, so a plural lookup cannot be aimed at a key that
 * has no plural forms.
 */
export type PluralKey =
  TranslationKey extends infer K
    ? K extends `${infer Base}_other`
      ? Base
      : never
    : never;

/** The CLDR plural categories, i.e. what `Intl.PluralRules.select()` returns. */
export type PluralCategory = Intl.LDMLPluralRule;

/**
 * English needs only `_one` and `_other`, and both are already required by the
 * `Record<TranslationKey, string>` half — so a locale declares only the EXTRA
 * categories its language uses.
 */
type EnglishCategories = "one" | "other";

/**
 * A complete dictionary for a language with the given plural categories.
 *
 * The `Record<TranslationKey, string>` half is what makes the compiler the
 * coverage tool: adding an English string fails `tsc -b` until every locale
 * has it. The second half closes the hole that leaves — without it only
 * English's OWN categories were required, so a Slovak or Polish dictionary
 * carrying just `_one`/`_other` compiled clean and shipped the wrong noun for
 * 2–4 of anything. (Verified: it did compile.)
 *
 * The declared categories are themselves checked against CLDR at test time
 * (see i18n.test.ts, "plural categories") — a type annotation can only enforce
 * what the author claims, and the author can claim the wrong set.
 */
export type DictionaryFor<Categories extends PluralCategory> =
  Record<TranslationKey, string> &
    Record<`${PluralKey}_${Exclude<Categories, EnglishCategories>}`, string>;

/** Erased shape for the lookup table, which does not care which locale it holds. */
export type Dictionary = Record<TranslationKey, string> &
  Partial<Record<`${PluralKey}_${PluralCategory}`, string>>;

export const DICTIONARIES: Record<Locale, Dictionary> = { en, cs };

export type Vars = Record<string, string | number>;

/**
 * Replace `{name}` with `vars.name`. An unknown placeholder is left VERBATIM
 * rather than blanked: `{email}` in the UI is a visible, reportable bug, while
 * an empty string reads as a design choice and ships unnoticed.
 *
 * `Object.hasOwn`, not `vars[name]` — the values can originate from user or
 * server data, and a bare index would resolve `{constructor}` off the
 * prototype. Same reflex as `utils/pieces.ts`.
 */
export function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.hasOwn(vars, name) ? String(vars[name]) : whole,
  );
}

/**
 * Constructing an `Intl.PluralRules` is not free and `tn()` can run inside a
 * render loop, so keep one per locale. Two entries, forever.
 */
const pluralRules = new Map<Locale, Intl.PluralRules>();
function rulesFor(locale: Locale): Intl.PluralRules {
  let rules = pluralRules.get(locale);
  if (!rules) {
    rules = new Intl.PluralRules(locale);
    pluralRules.set(locale, rules);
  }
  return rules;
}

/**
 * Raw string for `key`, falling back to English and then to the key itself.
 *
 * The fallback is defence in depth, not the coverage mechanism — the type
 * system already guarantees every locale is complete. It exists because
 * `localStorage` is user-writable and a persisted dictionary can go stale
 * across a deploy; showing English beats showing `auth.signIn` to a user.
 */
function lookup(locale: Locale, key: string): string {
  const dict = DICTIONARIES[locale] as Record<string, string | undefined>;
  return dict[key] ?? (en as Record<string, string | undefined>)[key] ?? key;
}

export interface I18n {
  /** Locale-independent BCP-47 tag, for `Intl` / `toLocaleDateString`. */
  locale: Locale;
  t: (key: TranslationKey, vars?: Vars) => string;
  /**
   * Plural-aware lookup. `count` is passed to `Intl.PluralRules` AND made
   * available as `{count}`, so `tn("time.minutes", 5)` needs no extra vars.
   */
  tn: (key: PluralKey, count: number, vars?: Vars) => string;
}

export function makeI18n(locale: Locale): I18n {
  return {
    locale,
    t: (key, vars) => interpolate(lookup(locale, key), vars),
    tn: (key, count, vars) => {
      const category = rulesFor(locale).select(count);
      const dict = DICTIONARIES[locale] as Record<string, string | undefined>;
      // `_other` is the guaranteed-present form (English defines it for every
      // plural base), so an unusual category in some future locale degrades to
      // a real sentence instead of the raw key.
      const template = dict[`${key}_${category}`] ?? lookup(locale, `${key}_other`);
      // The CATEGORY is locale-aware, so the NUMERAL has to be too, or Czech
      // reads "1.5 minuty" — correct noun, English decimal point. Selecting the
      // plural form and then rendering the number with `String()` is a
      // half-localized string, which is the kind of thing that survives review
      // precisely because the visible part looks translated.
      //
      // `count` goes LAST so it always wins. `count` is already a positional
      // argument here, so a caller passing it in `vars` too is passing it out
      // of habit from `t()`, not asking for the raw value — and spreading vars
      // afterwards would let that habit silently undo the formatting above.
      return interpolate(template, { ...vars, count: count.toLocaleString(locale) });
    },
  };
}

/**
 * The hook every component uses. Subscribing to the store here is what makes a
 * language switch re-render the tree — there is no provider to re-render it.
 */
export function useI18n(): I18n {
  const locale = useLocaleStore((s) => s.locale);
  return useMemo(() => makeI18n(locale), [locale]);
}

/**
 * Non-React access, for module-level helpers and event handlers that are not
 * inside a component. Reads the store imperatively, so it does NOT subscribe —
 * a value captured from here will not update on a language switch. Use
 * `useI18n()` in anything that renders.
 */
export function getI18n(): I18n {
  return makeI18n(useLocaleStore.getState().locale ?? DEFAULT_LOCALE);
}
