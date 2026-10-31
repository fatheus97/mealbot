import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_LOCALE, detectLocale, useLocaleStore } from '../store/useLocaleStore';

// public/lang-redirect.js is served as-is (a render-blocking classic script, not
// bundled), so it cannot import the store. These tests run the real file and
// hold it to the store's own record, so the two cannot drift.
const SCRIPT = readFileSync(resolve(process.cwd(), 'public/lang-redirect.js'), 'utf8');
const realLocation = window.location;

interface AcceptLanguageCase {
  header: string;
  languages: string[];
  czech: boolean;
}
const fixture = JSON.parse(
  readFileSync(resolve(process.cwd(), 'src/test/fixtures/accept-language.json'), 'utf8'),
) as { cases: AcceptLanguageCase[] };

/** Run the script as a page load would; returns where it went, or null. */
function visit(path: string, search = '', hash = ''): string | null {
  const replace = vi.fn();
  vi.stubGlobal('location', { pathname: path, search, hash, replace });
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

const choose = (locale: 'en' | 'cs') => useLocaleStore.getState().setLocale(locale);

beforeEach(() => {
  // setState persists, so reset the store BEFORE emptying storage.
  useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  localStorage.clear();
});

afterEach(() => {
  vi.stubGlobal('location', realLocation);
});

describe('browser language (decided by nginx, which this fixture also drives)', () => {
  it.each(fixture.cases.map((c) => [c.header || '(none)', c] as const))(
    'detectLocale agrees with the shared case for %s',
    (_, c) => {
      expect(detectLocale(c.languages)).toBe(c.czech ? 'cs' : 'en');
    },
  );

  it('each case lists its header tags as navigator.languages would', () => {
    for (const c of fixture.cases) {
      const tags = c.header
        .split(',')
        .map((part) => part.split(';')[0].trim())
        .filter(Boolean);
      expect(c.languages).toEqual(tags);
    }
  });

  it('the script never redirects on the browser language alone', () => {
    for (const path of ['/', '/privacy', '/terms', '/cs', '/cs/privacy', '/cs/terms']) {
      expect(visit(path)).toBeNull();
    }
  });
});

describe('a choice the visitor made', () => {
  it.each([
    ['/', '/cs'],
    ['/index.html', '/cs'],
    ['/privacy', '/cs/privacy'],
    ['/privacy.html', '/cs/privacy'],
    ['/terms/', '/cs/terms'],
  ])('Czech: %s -> %s', (path, target) => {
    choose('cs');
    expect(visit(path)).toBe(target);
  });

  it.each([
    ['/cs', '/'],
    ['/cs/', '/'],
    ['/cs/index.html', '/'],
    ['/cs/privacy', '/privacy'],
    ['/cs/terms.html', '/terms'],
  ])('English: %s -> %s', (path, target) => {
    choose('en');
    expect(visit(path)).toBe(target);
  });

  it('stays put on a page already in the chosen language, so it cannot loop', () => {
    choose('cs');
    expect(visit('/cs')).toBeNull();
    expect(visit('/cs/terms')).toBeNull();
    choose('en');
    expect(visit('/')).toBeNull();
    expect(visit('/privacy')).toBeNull();
  });

  it('keeps the query string and anchor, so campaign tags survive', () => {
    choose('cs');
    expect(visit('/', '?utm_source=fb&utm_campaign=x', '#pricing')).toBe(
      '/cs?utm_source=fb&utm_campaign=x#pricing',
    );
  });

  it('leaves pages with no counterpart alone', () => {
    choose('cs');
    for (const path of ['/app', '/app/plans', '/reset-password', '/csv']) {
      expect(visit(path)).toBeNull();
    }
  });

  it('a detected (not chosen) locale in storage is not a choice', () => {
    localStorage.setItem('mealbot-locale', JSON.stringify({ state: { locale: 'cs', explicit: false }, version: 1 }));
    expect(visit('/')).toBeNull();
  });

  it('an unreadable record is ignored rather than thrown on', () => {
    localStorage.setItem('mealbot-locale', '{not json');
    expect(visit('/')).toBeNull();
  });
});

describe('the language links record the choice', () => {
  it('in the record the app store reads back', async () => {
    visit('/');
    clickLink('cs');
    await useLocaleStore.persist.rehydrate();
    expect(useLocaleStore.getState()).toMatchObject({ locale: 'cs', explicit: true });
  });

  it('so the next visit lands in that language', () => {
    visit('/cs');
    clickLink('en');
    expect(visit('/cs/privacy')).toBe('/privacy');
  });

  it('when the click lands on an element inside the link', () => {
    visit('/');
    clickLink('cs', true);
    expect(visit('/')).toBe('/cs');
  });

  it('ignores links to languages the app does not have', () => {
    visit('/');
    clickLink('de');
    expect(localStorage.getItem('mealbot-locale')).toBeNull();
  });

  it('a browser that blocks storage gets no swap, and clicks do not throw', () => {
    const blocked = {
      getItem: () => {
        throw new Error('SecurityError');
      },
      setItem: () => {
        throw new Error('SecurityError');
      },
    };
    const realStorage = localStorage;
    // A listener's exception never reaches dispatchEvent; jsdom reports it on
    // window instead, so that is where to look for one.
    const uncaught: unknown[] = [];
    const onError = (event: ErrorEvent) => uncaught.push(event.error);
    window.addEventListener('error', onError);
    vi.stubGlobal('localStorage', blocked);
    try {
      expect(visit('/cs')).toBeNull();
      clickLink('en');
      expect(uncaught).toEqual([]);
    } finally {
      vi.stubGlobal('localStorage', realStorage);
      window.removeEventListener('error', onError);
    }
  });
});
