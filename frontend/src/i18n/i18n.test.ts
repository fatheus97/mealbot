import { describe, it, expect, beforeEach } from 'vitest';
import { makeI18n, interpolate, DICTIONARIES, type TranslationKey } from '.';
import { en } from './en';
import { MEAL_TYPES } from '../constants/mealTypes';
import { cs } from './cs';
import {
  useLocaleStore,
  detectLocale,
  mergePersistedLocale,
  DEFAULT_LOCALE,
  UI_LOCALES,
} from '../store/useLocaleStore';

describe('interpolate', () => {
  it('substitutes named placeholders', () => {
    expect(interpolate('sent to {email}', { email: 'a@b.c' })).toBe('sent to a@b.c');
  });

  it('substitutes numbers and repeated placeholders', () => {
    expect(interpolate('{n} of {n}', { n: 3 })).toBe('3 of 3');
  });

  it('leaves an unknown placeholder VISIBLE rather than blanking it', () => {
    // A hole in the sentence gets reported; a silent gap ships forever.
    expect(interpolate('hi {missing}', { other: 'x' })).toBe('hi {missing}');
  });

  it('does not resolve placeholders off Object.prototype', () => {
    // `vars` can carry server- or user-supplied values, so a bare index would
    // let `{constructor}` render a function body into the page.
    expect(interpolate('{constructor}', {})).toBe('{constructor}');
    expect(interpolate('{toString}', {})).toBe('{toString}');
  });

  it('returns the template untouched when there are no vars', () => {
    expect(interpolate('plain {x}')).toBe('plain {x}');
  });
});

describe('t', () => {
  it('returns the English string for the English locale', () => {
    expect(makeI18n('en').t('auth.signIn')).toBe('Sign In');
  });

  it('returns the Czech string for the Czech locale', () => {
    expect(makeI18n('cs').t('auth.signIn')).toBe('Přihlásit se');
  });

  it('interpolates', () => {
    expect(makeI18n('en').t('auth.error.register', { supportEmail: 'x@y.z' })).toContain('x@y.z');
    expect(makeI18n('cs').t('auth.error.register', { supportEmail: 'x@y.z' })).toContain('x@y.z');
  });

  it('falls back to English when a locale is missing the key', () => {
    // Cannot happen through the type system — this guards the runtime path for
    // a stale persisted locale or a partially-deployed bundle.
    const missing = makeI18n('cs').t('does.not.exist' as TranslationKey);
    expect(missing).toBe('does.not.exist');
  });
});

describe('tn — plural selection', () => {
  it('picks English one/other', () => {
    const { tn } = makeI18n('en');
    expect(tn('time.minutes', 1)).toBe('1 minute');
    expect(tn('time.minutes', 2)).toBe('2 minutes');
    expect(tn('time.minutes', 0)).toBe('0 minutes');
  });

  it('picks all four Czech categories', () => {
    // The reason this app cannot get away with an `n === 1 ? a : b` helper.
    const { tn } = makeI18n('cs');
    expect(tn('time.minutes', 1)).toBe('1 minuta');   // one
    expect(tn('time.minutes', 3)).toBe('3 minuty');   // few  (2–4)
    expect(tn('time.minutes', 5)).toBe('5 minut');    // other (5+)
    expect(tn('time.minutes', 0)).toBe('0 minut');    // other
  });

  it('renders the numeral in the locale, not just the noun', () => {
    // Half-localized output is the trap: the right Czech noun beside an
    // English decimal point ("1.5 minuty") reads as translated and is not.
    expect(makeI18n('cs').tn('time.minutes', 1.5)).toBe('1,5 minuty'); // many
    expect(makeI18n('en').tn('time.minutes', 1.5)).toBe('1.5 minutes');
  });

  it('agrees with Intl.PluralRules rather than hardcoding the boundaries', () => {
    // Pins the mechanism, not the numbers: if the CLDR data ever moves, this
    // fails loudly instead of the app quietly using the wrong noun.
    const rules = new Intl.PluralRules('cs');
    expect(rules.select(1)).toBe('one');
    expect(rules.select(4)).toBe('few');
    expect(rules.select(5)).toBe('other');
  });

  it('exposes count as {count} without the caller passing it', () => {
    expect(makeI18n('en').tn('time.minutes', 7)).toBe('7 minutes');
  });

  it('keeps the formatted numeral even if a caller also passes count in vars', () => {
    // `count` is already positional, so passing it again in `vars` is habit
    // carried over from t() — not a request for the raw value. If vars won,
    // the plural CATEGORY would still be Czech while the numeral silently
    // reverted to an English decimal point: the exact half-localized string
    // the formatting above exists to prevent.
    expect(makeI18n('cs').tn('time.minutes', 1.5, { count: 1.5 })).toBe('1,5 minuty');
  });
});

describe('translation parity', () => {
  const enKeys = Object.keys(en) as TranslationKey[];

  it('every English key has a Czech translation', () => {
    // Redundant with the compiler (cs is typed as a complete Dictionary), kept
    // because the failure message here names the missing keys directly.
    const missing = enKeys.filter((k) => !(k in cs));
    expect(missing).toEqual([]);
  });

  it('Czech introduces no key that English does not define', () => {
    // Catches a typo'd Czech key, which would otherwise sit unused and
    // invisible while the English fallback rendered in its place.
    const extra = Object.keys(cs).filter(
      (k) => !(k in en) && !/_(zero|two|few|many)$/.test(k),
    );
    expect(extra).toEqual([]);
  });

  it('every locale uses the same placeholders in a given key', () => {
    // The bug this catches: a translator drops `{supportEmail}` and the
    // sentence ships telling the user to contact nobody.
    const holes = (s: string) => (s.match(/\{(\w+)\}/g) ?? []).sort();
    const mismatched = enKeys
      .filter((k) => holes(en[k]).join() !== holes(cs[k]).join())
      .map((k) => `${k}: en=${holes(en[k])} cs=${holes(cs[k])}`);
    expect(mismatched).toEqual([]);
  });

  it('no translation is left as the untranslated English string', () => {
    // Catches a copy-paste that never got translated. The allowlist is
    // deliberately explicit and deliberately annoying to extend: every entry is
    // a claim that two languages genuinely coincide, which is exactly the claim
    // a rushed translator makes about a word they simply did not translate.
    const SAME_IN_BOTH: TranslationKey[] = [
      'auth.busy', // "..." — punctuation
      'mealType.brunch', // loanword; Czech uses "brunch" too
    ];
    const identical = enKeys.filter((k) => en[k] === cs[k]);
    expect(identical.sort()).toEqual([...SAME_IN_BOTH].sort());
  });
});

describe('locale store', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it('detects a supported language from the browser preference list', () => {
    expect(detectLocale(['cs-CZ', 'en-US'])).toBe('cs');
  });

  it('matches on the primary subtag only', () => {
    expect(detectLocale(['CS-cz'])).toBe('cs');
    expect(detectLocale(['cs-Latn-CZ'])).toBe('cs');
  });

  it('walks past languages we do not ship', () => {
    expect(detectLocale(['sk-SK', 'de-DE', 'cs'])).toBe('cs');
  });

  it('falls back to the default when nothing matches', () => {
    expect(detectLocale(['ja-JP'])).toBe(DEFAULT_LOCALE);
    expect(detectLocale([])).toBe(DEFAULT_LOCALE);
  });

  it('ignores non-string entries rather than throwing', () => {
    expect(detectLocale([undefined as unknown as string, 'cs'])).toBe('cs');
  });

  it('marks the choice explicit so detection cannot override it later', () => {
    useLocaleStore.getState().setLocale('cs');
    expect(useLocaleStore.getState()).toMatchObject({ locale: 'cs', explicit: true });
  });

  it('ships exactly the locales that have a dictionary', () => {
    expect([...UI_LOCALES].sort()).toEqual(['cs', 'en']);
  });
});

describe('meal type labels', () => {
  // MEAL_TYPES mirrors the backend enum and grows there first. A new value with
  // no `mealType.*` key would render its RAW ENUM NAME into a dropdown —
  // "side_dish" — which looks like a bug in the data rather than a missing
  // translation, so nobody would think to look here.
  it('covers exactly the meal types the app knows about', () => {
    const keyed = Object.keys(en)
      .filter((k) => k.startsWith('mealType.'))
      .map((k) => k.slice('mealType.'.length))
      .sort();
    expect(keyed).toEqual([...MEAL_TYPES].sort());
  });

  it('translates every one of them', () => {
    for (const mt of MEAL_TYPES) {
      const key = `mealType.${mt}` as TranslationKey;
      expect(makeI18n('cs').t(key)).not.toBe(key);
    }
  });
});

describe('plural categories', () => {
  // The type annotation on a dictionary can only enforce what its AUTHOR
  // claimed. Declare `DictionaryFor<"one" | "other">` for Slovak and the
  // compiler is satisfied while the language quietly needs four forms. This
  // asks CLDR instead, so it holds for locales nobody has added yet.
  const PROBES = [
    ...Array.from({ length: 25 }, (_, i) => i), // 0–24: one/two/few/other
    100, 101, 102, 111, 1000, // large-number categories (Welsh, Arabic, Russian)
    0.5, 1.5, 2.5, 1.1, // decimals — Czech "many"
  ];

  const pluralBases = [
    ...new Set(
      Object.keys(en)
        .filter((k) => k.endsWith('_other'))
        .map((k) => k.slice(0, -'_other'.length)),
    ),
  ];

  it('has a plural base to check', () => {
    // Guards the guard: if every plural key were deleted, the loop below would
    // pass vacuously and this suite would claim a coverage it never tested.
    expect(pluralBases.length).toBeGreaterThan(0);
  });

  for (const locale of UI_LOCALES) {
    it(`${locale} defines every form Intl.PluralRules can actually select`, () => {
      const rules = new Intl.PluralRules(locale);
      const needed = [...new Set(PROBES.map((n) => rules.select(n)))].sort();
      const dict = DICTIONARIES[locale] as Record<string, string | undefined>;

      const missing = pluralBases.flatMap((base) =>
        needed.filter((cat) => dict[`${base}_${cat}`] === undefined).map((cat) => `${base}_${cat}`),
      );
      expect({ locale, needed, missing }).toMatchObject({ missing: [] });
    });
  }

  it('knows Czech needs four forms and English two', () => {
    // Pins the premise the whole design rests on, so a change in the CLDR data
    // shows up here rather than as a wrong noun in the UI.
    const cats = (loc: string) =>
      [...new Set(PROBES.map((n) => new Intl.PluralRules(loc).select(n)))].sort();
    expect(cats('en')).toEqual(['one', 'other']);
    expect(cats('cs')).toEqual(['few', 'many', 'one', 'other']);
  });
});

describe('rehydration', () => {
  // `current` is what detection produced this visit; `persisted` is last visit.
  const detected = { locale: 'cs', explicit: false } as const;

  it('honours a deliberate choice over what the browser now says', () => {
    expect(
      mergePersistedLocale({ locale: 'en', explicit: true }, { ...detected }),
    ).toMatchObject({ locale: 'en', explicit: true });
  });

  it('re-detects when the saved value was itself only a detection result', () => {
    // The stuck-locale bug: a user whose first visit resolved to English and
    // who later switches their BROWSER to Czech should get Czech, not be
    // pinned forever by a guess nobody made.
    expect(
      mergePersistedLocale({ locale: 'en', explicit: false }, { ...detected }),
    ).toMatchObject({ locale: 'cs', explicit: false });
  });

  it('ignores a locale we do not ship', () => {
    // localStorage is user-writable; an unknown locale renders every key raw.
    expect(
      mergePersistedLocale({ locale: 'xx', explicit: true }, { ...detected }),
    ).toMatchObject({ locale: 'cs' });
  });

  it('survives corrupted or absent persisted state', () => {
    for (const junk of [undefined, null, {}, 'nonsense', 42, { locale: 5, explicit: true }]) {
      expect(mergePersistedLocale(junk, { ...detected })).toMatchObject({ locale: 'cs' });
    }
  });
});
