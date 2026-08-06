/// <reference types="node" />
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { en } from './en';

/**
 * Every dictionary key must actually be USED somewhere.
 *
 * ─── Why this exists ────────────────────────────────────────────────────────
 * `untranslatedEnglishIn` catches the reverse — a rendered English string that
 * has a key — and is blind to a key that exists but was never wired up. Both
 * happened in the same PR: `calendar.plan` was added for a specific fallback
 * and the call site was never changed, so the dictionary looked complete while
 * the component still rendered "Plan". No render test could see it, because
 * the key and the literal are identical in English; only Czech reveals it, and
 * only in the branch that renders that fallback.
 *
 * An orphan key is also pure cost: a translator maintains it forever, and the
 * next reader assumes the string it names is handled.
 */

/** Every non-test .ts/.tsx under a directory. */
function walkSource(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return walkSource(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\./.test(entry.name) ? [full] : [];
  });
}

const SRC = resolve(process.cwd(), 'src');
const sources = walkSource(SRC)
  // The dictionaries define the keys; referencing themselves proves nothing.
  .filter((f) => !/[\\/]i18n[\\/](en|cs)\.ts$/.test(f))
  .map((f) => readFileSync(f, 'utf-8'));
const haystack = sources.join('\n');

/** Keys named by a literal — `t("auth.signIn")`, `"plans.loading"`. */
const literalKeys = new Set(
  [...haystack.matchAll(/["'`]([a-z][a-zA-Z]*\.[a-zA-Z0-9_.]+)["'`]/g)].map((m) => m[1]),
);

/**
 * Prefixes used dynamically — `` t(`mealType.${mt}`) ``. Every key under such a
 * prefix counts as used, because the value comes from an enum at runtime and
 * cannot be matched literally. Those enums have their OWN parity test in
 * i18n.test.ts, so nothing is left unguarded by this allowance.
 */
const dynamicPrefixes = [
  ...haystack.matchAll(/[`"']([a-z][a-zA-Z]*\.)\$\{/g),
].map((m) => m[1]);

/** Plural bases are referenced without their `_one` / `_other` suffix. */
const pluralBases = new Set(
  [...literalKeys].filter((k) => haystack.includes(`"${k}"`) || haystack.includes(`'${k}'`)),
);

describe('dictionary key usage', () => {
  it('found source files and key references to check', () => {
    // Guards the guard: a broken walk or regex would make the assertion below
    // pass over an empty set, which is the exact failure this file is about.
    expect(sources.length).toBeGreaterThan(50);
    expect(literalKeys.size).toBeGreaterThan(100);
  });

  it('has no orphan keys — every key is referenced in source', () => {
    const orphans = (Object.keys(en) as string[]).filter((key) => {
      if (literalKeys.has(key)) return false;
      // `time.minutes_one` is reached via tn("time.minutes", n).
      const base = key.replace(/_(zero|one|two|few|many|other)$/, '');
      if (base !== key && (literalKeys.has(base) || pluralBases.has(base))) return false;
      return !dynamicPrefixes.some((prefix) => key.startsWith(prefix));
    });
    expect(orphans).toEqual([]);
  });
});
