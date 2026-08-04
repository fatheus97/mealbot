import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * UI locales the app actually ships translations for.
 *
 * Deliberately NOT the same list as the backend's SUPPORTED_LANGUAGES (33
 * entries, see backend/app/core/language_whitelist.py). That list controls what
 * language the LLM WRITES RECIPES IN — the model can write Japanese without
 * anyone translating a single button. This list is what the app's own chrome
 * has been translated into by hand, so it grows one careful PR at a time.
 *
 * Keeping them separate is the point: a user can read Japanese recipes through
 * an English UI today, and nothing here has to lie about that.
 */
export const UI_LOCALES = ['en', 'cs'] as const;
export type Locale = (typeof UI_LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'en';

/** Endonyms — a language is named in itself, never in English. */
export const LOCALE_NAMES: Record<Locale, string> = {
  en: 'English',
  cs: 'Čeština',
};

function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (UI_LOCALES as readonly string[]).includes(value);
}

/**
 * Best UI locale for a fresh visitor, from the browser's language preferences.
 *
 * Matches on the PRIMARY SUBTAG only: "cs-CZ", "cs", and a hypothetical
 * "cs-Latn-CZ" all mean Czech. Walks `navigator.languages` in order so a user
 * whose first preference we do not translate still gets their second.
 *
 * Runs before any user record exists, which is the whole reason UI locale is
 * client-side state: the landing page, login and register screens have no
 * profile to read a preference from.
 */
export function detectLocale(
  languages: readonly string[] = typeof navigator === 'undefined'
    ? []
    : (navigator.languages ?? [navigator.language]),
): Locale {
  for (const tag of languages) {
    if (typeof tag !== 'string') continue;
    const primary = tag.toLowerCase().split('-')[0];
    if (isLocale(primary)) return primary;
  }
  return DEFAULT_LOCALE;
}

interface LocaleState {
  locale: Locale;
  /**
   * Whether the user picked this locale themselves.
   *
   * Load-bearing: an explicit choice must survive everything. Without this flag
   * a returning Czech-browser user who deliberately switched to English would be
   * flipped back to Czech on their next visit by detection, with no way to make
   * it stick — the classic "the site keeps overriding me" bug.
   */
  explicit: boolean;
  setLocale: (locale: Locale) => void;
}

/**
 * Decide the locale to start with, given what was persisted and what detection
 * just produced. Exported so it can be tested directly — driving it through a
 * real rehydration would mean stubbing localStorage and remounting the store.
 */
export function mergePersistedLocale<T extends Pick<LocaleState, "locale" | "explicit">>(
  persisted: unknown,
  current: T,
): T {
  const saved = persisted as Partial<LocaleState> | undefined;
  if (saved?.explicit !== true || !isLocale(saved.locale)) return current;
  return { ...current, locale: saved.locale, explicit: true };
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      // Detection only supplies the INITIAL value. Once `explicit` is true the
      // persisted locale wins and detection never runs again for that browser.
      locale: detectLocale(),
      explicit: false,
      setLocale: (locale) => set({ locale, explicit: true }),
    }),
    {
      name: 'mealbot-locale',
      version: 1,
      merge: mergePersistedLocale,
    },
  ),
);
