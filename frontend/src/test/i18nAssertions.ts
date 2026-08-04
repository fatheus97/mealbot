import { en } from '../i18n/en';
import { cs } from '../i18n/cs';
import type { TranslationKey } from '../i18n';

/**
 * Keys whose English value is expected to survive into a Czech render.
 *
 * The language picker stores the English EXONYM the backend whitelist accepts,
 * so its examples and datalist options really are "Czech", not "Čeština" —
 * translating them would offer a value the form rejects.
 */
const EXPECTED_IN_EVERY_LOCALE: readonly TranslationKey[] = ['prefs.languagePlaceholder'];

/**
 * Every English string still visible in `root` after switching to Czech.
 *
 * ⚠️ SCOPE: this sees only what is IN THE DOM when it runs. Anything behind a
 * `{cond && …}` — a confirm dialog, a success notice, an error branch — is
 * invisible to it, and a passing result says nothing about those. Verified by
 * negative control: replacing a string inside SettingsPopup's confirm-discard
 * block with English does NOT fail this check, while doing the same to a
 * string rendered by default does.
 *
 * That is the exact shape of the bug this file exists because of — a
 * getComputedStyle sweep of one modal state was reported as coverage of the
 * component. Assert conditional branches by driving them open first.
 *
 * ─── Why not "detect English" ───────────────────────────────────────────────
 * The obvious version — regex the rendered text for something that looks
 * English — is really an ASCII detector, and Czech is full of ASCII: it flags
 * "Jednotky v postupu" and "Zaregistrovat se" while missing any English string
 * that happens to contain a diacritic. It cannot be tuned into correctness,
 * because "does this text look English" is not a question a character class can
 * answer.
 *
 * This asks the exact question instead: does the DOM contain a string that we
 * have an English value for, and a DIFFERENT Czech value for? That has no false
 * positives on Czech text and no false negatives on English text.
 *
 * Short strings are skipped — a 4-character English value like "Add" appears
 * inside unrelated Czech words by coincidence, and the substring match would be
 * meaningless rather than wrong.
 */
export function untranslatedEnglishIn(root: HTMLElement, minLength = 8): string[] {
  const text = root.textContent ?? '';
  const found: string[] = [];

  for (const [key, english] of Object.entries(en) as [TranslationKey, string][]) {
    if (english.length < minLength) continue;
    if (EXPECTED_IN_EVERY_LOCALE.includes(key)) continue;
    // Identical in both languages (loanwords, punctuation) — its presence
    // proves nothing either way.
    if (cs[key] === english) continue;
    // Placeholders are filled at render, so compare the literal prefix only.
    const literal = english.split('{')[0].trim();
    if (literal.length < minLength) continue;
    if (text.includes(literal)) found.push(`${key}: ${literal}`);
  }
  return found;
}
