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

let addressBar: ReturnType<typeof vi.spyOn>;

/** Run the script as a page load would; returns where it went, or null. */
function visit(path: string, search = '', hash = ''): string | null {
  const replace = vi.fn();
  vi.stubGlobal('location', { pathname: path, search, hash, replace });
  addressBar.mockClear();
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
  // The real history would move jsdom's own URL under the other tests.
  addressBar = vi.spyOn(window.history, 'replaceState').mockImplementation(() => {});
  // setState persists, so reset the store BEFORE emptying storage.
  useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  localStorage.clear();
});

afterEach(() => {
  vi.stubGlobal('location', realLocation);
  addressBar.mockRestore();
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
    expect(visit(path)).toBe(`${target}?lang=cs`);
  });

  it.each([
    ['/cs', '/'],
    ['/cs/', '/'],
    ['/cs/index.html', '/'],
    ['/cs/privacy', '/privacy'],
    ['/cs/terms.html', '/terms'],
  ])('English: %s -> %s', (path, target) => {
    choose('en');
    expect(visit(path)).toBe(`${target}?lang=en`);
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
      '/cs?utm_source=fb&utm_campaign=x&lang=cs#pricing',
    );
  });

  it('marks the swap with ?lang=, which nginx honours, so no Referer is needed to stop a loop', () => {
    // A browser that sends no Referer: / -> 302 /cs -> this swap. Without the
    // marker nginx would answer the swap with the same 302, forever.
    choose('en');
    expect(visit('/cs')).toBe('/?lang=en');
    expect(visit('/cs', '?lang=cs&utm_source=x')).toBe('/?utm_source=x&lang=en');
  });

  it('strips the marker from the address bar on arrival, keeping everything else', () => {
    choose('en');
    expect(visit('/', '?utm_source=fb&lang=en', '#faq')).toBeNull();
    expect(addressBar).toHaveBeenCalledWith(null, '', '/?utm_source=fb#faq');
    expect(visit('/', '?lang=en')).toBeNull();
    expect(addressBar).toHaveBeenLastCalledWith(null, '', '/');
  });

  it('leaves the address bar alone when there is no marker', () => {
    choose('en');
    expect(visit('/', '?utm_source=fb')).toBeNull();
    expect(addressBar).not.toHaveBeenCalled();
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
    expect(visit('/cs/privacy')).toBe('/privacy?lang=en');
  });

  it('when the click lands on an element inside the link', () => {
    visit('/');
    clickLink('cs', true);
    expect(visit('/')).toBe('/cs?lang=cs');
  });

  it('carries the campaign tags over to the other language', () => {
    visit('/', '?utm_source=fb&utm_campaign=x');
    const link = document.createElement('a');
    link.setAttribute('hreflang', 'cs');
    link.setAttribute('href', '/cs');
    // jsdom cannot navigate; the script's capture listener has run by then.
    link.addEventListener('click', (event) => event.preventDefault());
    document.body.appendChild(link);
    link.click();
    link.click(); // a second click must not append the query twice
    link.remove();
    expect(link.getAttribute('href')).toBe('/cs?utm_source=fb&utm_campaign=x');
  });

  it('leaves the link alone when there is no query string', () => {
    visit('/');
    const link = document.createElement('a');
    link.setAttribute('hreflang', 'cs');
    link.setAttribute('href', '/cs');
    link.addEventListener('click', (event) => event.preventDefault());
    document.body.appendChild(link);
    link.click();
    link.remove();
    expect(link.getAttribute('href')).toBe('/cs');
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

describe("the landings' links to the legal pages keep their Referer", () => {
  // nginx keys "came from this site" on the Referer. A noreferrer link from the
  // English landing reaches /terms looking external, so a Czech browser gets the
  // Czech contract in the middle of an English signup. (The app's own links keep
  // noreferrer on purpose: an /app URL can carry a single-use token, and nginx
  // logs the Referer in full.)
  it.each(['index.html', 'cs/index.html'])('%s', (page) => {
    const html = readFileSync(resolve(process.cwd(), page), 'utf8');
    const legal = [...html.matchAll(/<a\b[^>]*href="\/(?:cs\/)?(?:terms|privacy)"[^>]*>/g)].map((m) => m[0]);
    expect(legal.length).toBeGreaterThan(0);
    for (const tag of legal) expect(tag).not.toMatch(/noreferrer/);
  });
});
