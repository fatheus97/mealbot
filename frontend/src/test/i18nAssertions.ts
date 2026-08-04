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
 * Matching is WHOLE-WORD, not raw substring. The first version used a bare
 * `includes` and needed an 8-character floor to stop coincidental hits — which
 * silently exempted "Steps", "Frozen", "Cook", "Save", "Cancel" and most other
 * button labels. Negative-controlling the callers is what exposed that: putting
 * English back in two components did not fail their tests. Word boundaries let
 * the floor drop to 4 without the collisions it was there to prevent.
 *
 * Values shorter than `minLength` are still skipped: a 1–3 character label ("g",
 * "min", "OK") collides with real content — ingredient units, meal names — often
 * enough that a hit would not mean anything.
 */
export function untranslatedEnglishIn(root: HTMLElement, minLength = 4): string[] {
  // NOTE: the result is a list of KEYS, not of distinct strings. One rendered
  // string can match several — an untranslated "Ingredients:" reports under
  // `meal.ingredients`, `cook.ingredients` AND `editor.ingredients`, because
  // all three have that English value and whole-word matching finds the
  // shorter ones inside it. Every entry is a genuine match; the LENGTH is not
  // a count of things to fix. Read the failure, do not tally it.
  const found: string[] = [];
  const haystacks = visibleStrings(root);

  for (const [key, english] of Object.entries(en) as [TranslationKey, string][]) {
    if (EXPECTED_IN_EVERY_LOCALE.includes(key)) continue;
    // Identical in both languages (loanwords, unit symbols) — its presence
    // proves nothing either way.
    if (cs[key] === english) continue;
    // Placeholders are filled at render, so compare the literal prefix only.
    const literal = english.split('{')[0].trim();
    if (literal.length < minLength) continue;
    const escaped = literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Anchor on "not a letter" rather than \b — a value can start or end on
    // punctuation ("+ Add step", "Ingredients:") where \b does not apply.
    const pattern = new RegExp(`(^|[^\\p{L}])${escaped}([^\\p{L}]|$)`, 'u');
    if (haystacks.some((h) => pattern.test(h))) found.push(`${key}: ${literal}`);
  }
  return found;
}

/**
 * Each text node and user-facing attribute as its own string.
 *
 * NOT `root.textContent`: that concatenates every node with no separator, so
 * "…gramech" followed by a `<legend>Steps</legend>` becomes "…gramechSteps"
 * and the word-boundary match fails. The first version of this function did
 * exactly that, and its negative control passed — English put back in two
 * components did not fail their tests. Per-node strings restore real
 * boundaries.
 *
 * Attributes are included because `aria-label`, `placeholder` and `title` are
 * user-facing and never appear in `textContent` at all.
 */
function visibleStrings(root: HTMLElement): string[] {
  const out: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const value = n.nodeValue?.trim();
    if (value) out.push(value);
  }
  for (const el of root.querySelectorAll('[aria-label],[placeholder],[title],[alt]')) {
    for (const attr of ['aria-label', 'placeholder', 'title', 'alt']) {
      const value = el.getAttribute(attr)?.trim();
      if (value) out.push(value);
    }
  }
  return out;
}
