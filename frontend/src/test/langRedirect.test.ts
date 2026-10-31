import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_LOCALE, detectLocale, useLocaleStore } from '../store/useLocaleStore';

// public/lang-redirect.js is served as-is (a render-blocking classic script, not
// bundled), so it cannot import detectLocale or the store. These tests run the
// real file and hold it to both, so the copy cannot drift.
const SCRIPT = readFileSync(resolve(process.cwd(), 'public/lang-redirect.js'), 'utf8');
const ORIGIN = 'https://trymealbot.com';
const realLocation = window.location;
const realNavigator = window.navigator;

interface Visit {
  path: string;
  languages?: readonly unknown[];
  referrer?: string;
  search?: string;
  hash?: string;
}

/** Run the script as a page load would; returns where it redirected, or null. */
function visit({ path, languages = ['en-US'], referrer = '', search = '', hash = '' }: Visit): string | null {
  const replace = vi.fn();
  vi.stubGlobal('location', { origin: ORIGIN, pathname: path, search, hash, replace });
  vi.stubGlobal('navigator', { languages, language: languages[0] });
  Object.defineProperty(document, 'referrer', { configurable: true, value: referrer });
  new Function(SCRIPT)();
  return replace.mock.calls.length ? (replace.mock.calls[0][0] as string) : null;
}

function clickLink(hreflang: string, inner = false): void {
  const link = document.createElement('a');
  link.setAttribute('hreflang', hreflang);
  const target = inner ? link.appendChild(document.createElement('span')) : link;
  document.body.appendChild(link);
  target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  link.remove();
}

beforeEach(() => {
  // setState persists, so reset the store BEFORE emptying storage.
  useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  localStorage.clear();
});

afterEach(() => {
  vi.stubGlobal('location', realLocation);
  vi.stubGlobal('navigator', realNavigator);
  Reflect.deleteProperty(document, 'referrer');
});

describe('lang-redirect.js agrees with detectLocale', () => {
  const CASES: readonly (readonly unknown[])[] = [
    ['cs-CZ'], ['CS'], ['cs-Latn-CZ'], ['sk-SK'], ['sk'], ['en-US'], ['en-GB', 'sk'],
    ['de-DE', 'cs'], ['pl-PL', 'sk-SK'], ['ja-JP'], [], [undefined, 'cs'],
  ];
  it.each(CASES.map((langs) => [JSON.stringify(langs), langs]))(
    'browser %s',
    (_, langs) => {
      const czech = detectLocale(langs as readonly string[]) === 'cs';
      expect(visit({ path: '/', languages: langs })).toBe(czech ? '/cs' : null);
    },
  );

  it('sends Slovak browsers to Czech', () => {
    expect(visit({ path: '/', languages: ['sk-SK', 'en-US'] })).toBe('/cs');
  });
});

describe('where it redirects', () => {
  it.each([
    ['/', '/cs'],
    ['/index.html', '/cs'],
    ['/privacy', '/cs/privacy'],
    ['/privacy.html', '/cs/privacy'],
    ['/terms', '/cs/terms'],
    ['/terms/', '/cs/terms'],
  ])('%s -> %s for a Czech browser', (path, target) => {
    expect(visit({ path, languages: ['cs-CZ'] })).toBe(target);
  });

  it('keeps the query string and anchor, so campaign tags survive', () => {
    expect(
      visit({ path: '/', languages: ['cs'], search: '?utm_source=fb&utm_campaign=x', hash: '#pricing' }),
    ).toBe('/cs?utm_source=fb&utm_campaign=x#pricing');
  });

  it.each(['/cs', '/cs/', '/cs/privacy', '/cs/terms', '/app', '/app/plans', '/reset-password'])(
    'never redirects from %s',
    (path) => {
      expect(visit({ path, languages: ['cs-CZ'] })).toBeNull();
    },
  );

  it('leaves an English browser on the English page', () => {
    expect(visit({ path: '/', languages: ['en-US', 'de'] })).toBeNull();
  });
});

describe('a choice the visitor made wins over the browser', () => {
  it('English picked in the app keeps a Czech browser on the English landing', () => {
    useLocaleStore.getState().setLocale('en');
    expect(visit({ path: '/', languages: ['cs-CZ'] })).toBeNull();
  });

  it('Czech picked in the app sends an English browser to /cs', () => {
    useLocaleStore.getState().setLocale('cs');
    expect(visit({ path: '/', languages: ['en-US'] })).toBe('/cs');
  });

  it('a detected (not chosen) locale in storage does not count as a choice', () => {
    localStorage.setItem('mealbot-locale', JSON.stringify({ state: { locale: 'cs', explicit: false }, version: 1 }));
    expect(visit({ path: '/', languages: ['en-US'] })).toBeNull();
  });

  it('an unreadable record falls back to detection instead of throwing', () => {
    localStorage.setItem('mealbot-locale', '{not json');
    expect(visit({ path: '/', languages: ['cs'] })).toBe('/cs');
  });

  it('a visitor arriving from one of our Czech pages is not bounced back', () => {
    // Covers a browser that blocks storage: the click below could not be saved.
    expect(visit({ path: '/', languages: ['cs'], referrer: `${ORIGIN}/cs` })).toBeNull();
    expect(visit({ path: '/privacy', languages: ['cs'], referrer: `${ORIGIN}/cs/terms` })).toBeNull();
  });

  it('a referrer that is not one of our Czech pages does not stop the redirect', () => {
    expect(visit({ path: '/', languages: ['cs'], referrer: 'https://example.com/cs' })).toBe('/cs');
    expect(visit({ path: '/', languages: ['cs'], referrer: `${ORIGIN}/csv-export` })).toBe('/cs');
    expect(visit({ path: '/', languages: ['cs'], referrer: `${ORIGIN}/` })).toBe('/cs');
  });
});

describe('the language link records the choice', () => {
  it('in the record the app store reads back', async () => {
    visit({ path: '/', languages: ['en-US'] });
    clickLink('cs');
    await useLocaleStore.persist.rehydrate();
    expect(useLocaleStore.getState()).toMatchObject({ locale: 'cs', explicit: true });
  });

  it('so English clicked on /cs keeps a Czech browser on / next time', () => {
    visit({ path: '/cs', languages: ['cs'] });
    clickLink('en');
    expect(visit({ path: '/', languages: ['cs'] })).toBeNull();
  });

  it('when the click lands on an element inside the link', () => {
    visit({ path: '/', languages: ['en'] });
    clickLink('cs', true);
    expect(visit({ path: '/', languages: ['en'] })).toBe('/cs');
  });

  it('ignores links to languages the app does not have', () => {
    visit({ path: '/', languages: ['en'] });
    clickLink('de');
    expect(localStorage.getItem('mealbot-locale')).toBeNull();
  });

  it('a browser that blocks storage still gets detection, and clicks do not throw', () => {
    const blocked = {
      getItem: () => { throw new Error('SecurityError'); },
      setItem: () => { throw new Error('SecurityError'); },
    };
    const realStorage = localStorage;
    // A listener's exception never reaches dispatchEvent; jsdom reports it on
    // window instead, so that is where to look for one.
    const uncaught: unknown[] = [];
    const onError = (event: ErrorEvent) => uncaught.push(event.error);
    window.addEventListener('error', onError);
    vi.stubGlobal('localStorage', blocked);
    try {
      expect(visit({ path: '/', languages: ['cs'] })).toBe('/cs');
      clickLink('en');
      expect(uncaught).toEqual([]);
    } finally {
      vi.stubGlobal('localStorage', realStorage);
      window.removeEventListener('error', onError);
    }
  });
});
