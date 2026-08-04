import { useLocaleStore } from "../store/useLocaleStore";

/**
 * Keep `<html lang>` in step with the chosen UI locale.
 *
 * Assistive tech reads the attribute to pick pronunciation rules, so Czech
 * copy left under `lang="en"` is spoken with English phonetics — the text is
 * technically present and practically unusable. Browsers also key hyphenation
 * and spellcheck off it.
 *
 * Returns the unsubscribe function so a test can tear the listener down; the
 * app calls it once at bootstrap and never unsubscribes.
 */
export function syncDocumentLang(): () => void {
  const apply = (locale: string) => {
    document.documentElement.lang = locale;
  };
  apply(useLocaleStore.getState().locale);
  return useLocaleStore.subscribe((state) => apply(state.locale));
}
