/// <reference types="node" />
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { contrastRatio, wcagAAFloor, checkText, blend, adaptiveText, THEME } from './contrast';
import {
  SURFACE,
  NOTICE_OK_COLOR,
  NOTICE_ERROR_COLOR,
  MUTED_COLOR,
} from '../components/PantryStaples';
import { PAGE_TEXT, MUTED_PAGE_OPACITY, type ThemeName } from '../constants/theme';

describe('contrast maths', () => {
  it('agrees with the WCAG reference values', () => {
    // Pins the formula itself. Without these, a bug in `luminance` would make
    // every assertion below pass for the wrong reason.
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
    expect(contrastRatio('#767676', '#ffffff')).toBeCloseTo(4.54, 1);
  });

  it('is symmetric — foreground vs background role does not matter', () => {
    // The exact reasoning that made #16a34a a bug twice: it was fixed as a
    // background and left as a foreground, as if the ratio depended on which.
    expect(contrastRatio('#15803d', '#ffffff')).toBeCloseTo(
      contrastRatio('#ffffff', '#15803d'),
      10,
    );
  });

  it('only grants the 3:1 large-text floor to genuinely large text', () => {
    expect(wcagAAFloor(13.6)).toBe(4.5);
    expect(wcagAAFloor(16, 700)).toBe(4.5); // bold but under 18.66px
    expect(wcagAAFloor(18.66, 700)).toBe(3);
    expect(wcagAAFloor(24)).toBe(3);
  });
});

describe('pantry staples colours', () => {
  // These are checked as CONSTANTS rather than through the DOM on purpose. The
  // notice colours only render after a save or a failure, so a
  // getComputedStyle sweep of the open modal cannot see them — which is exactly
  // how #16a34a survived one, at 3.29:1, while the sweep reported "nothing
  // below AA".
  const cases: [string, string][] = [
    ['success notice', NOTICE_OK_COLOR],
    ['error notice', NOTICE_ERROR_COLOR],
    ['muted help text', MUTED_COLOR],
  ];

  for (const [name, color] of cases) {
    it(`${name} meets WCAG AA on the modal surface`, () => {
      const result = checkText(color, SURFACE, 13.6);
      expect(result).toMatchObject({ passes: true });
    });
  }

  it('the save button meets AA with the surface as its foreground', () => {
    // Inverted pair: white text on the green fill.
    expect(checkText(SURFACE, NOTICE_OK_COLOR, 14.4)).toMatchObject({ passes: true });
  });

  it('rejects the colour that shipped this bug', () => {
    // A negative control on the check itself. If this ever passes, the floor or
    // the maths has drifted and every assertion above is worthless.
    expect(checkText('#16a34a', SURFACE, 13.6).passes).toBe(false);
  });
});

describe('theme surfaces', () => {
  // THEME is a hand-copy of index.css. If someone restyles the page background
  // there, every ratio below silently starts measuring against a surface the app
  // no longer paints — so pin the two together.
  const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf-8').replace(
    /\/\*[\s\S]*?\*\//g,
    '',
  );
  const rootBlock = (source: string) => {
    const open = source.indexOf('{', source.indexOf(':root'));
    return source.slice(open + 1, source.indexOf('}', open));
  };

  it('matches the dark default in index.css :root', () => {
    const root = rootBlock(css);
    expect(root).toMatch(new RegExp(`background-color:\\s*${THEME.dark.bg}\\b`, 'i'));
    // `:root` is dark FIRST — light is the @media override, not the other way
    // round. Getting this backwards is what makes a "looks fine on my machine"
    // check pass while dark mode is broken.
    const [, r, g, b, a] = /color:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/.exec(root)!;
    expect(`#${[r, g, b].map((v) => Number(v).toString(16).padStart(2, '0')).join('')}`).toBe(
      THEME.dark.fg,
    );
    expect(Number(a)).toBe(THEME.dark.fgAlpha);
  });

  it('matches the light override in index.css', () => {
    const light = rootBlock(css.slice(css.indexOf('@media (prefers-color-scheme: light)')));
    expect(light).toMatch(new RegExp(`background-color:\\s*${THEME.light.bg}\\b`, 'i'));
    expect(light).toMatch(new RegExp(`(?<!-)color:\\s*${THEME.light.fg}\\b`, 'i'));
    expect(THEME.light.fgAlpha).toBe(1);
  });

  it('composites a translucent foreground before measuring it', () => {
    // Pins `blend` itself — without this, every adaptiveText() assertion below
    // could be measuring the wrong colour and still "pass".
    expect(blend('#ffffff', 1, '#000000')).toBe('#ffffff');
    expect(blend('#ffffff', 0, '#000000')).toBe('#000000');
    expect(blend('#ffffff', 0.5, '#000000')).toBe('#808080');
    // index.css's own rgba(255,255,255,0.87) over #242424.
    expect(adaptiveText('dark')).toBe('#e3e3e3');
    // Light mode's default text is opaque, so it flattens to itself.
    expect(adaptiveText('light')).toBe(THEME.light.fg);
  });
});

describe('colours on the adaptive page background', () => {
  // These sit on the page background rather than on a card or modal, so the
  // surface under them CHANGES with the OS theme while the inline style does
  // not. Each one is therefore checked against BOTH surfaces — the single-
  // surface check that covers PantryStaples above would pass every one of these
  // on white and miss the entire bug.
  const schemes: ThemeName[] = ['light', 'dark'];

  for (const [name, pair] of Object.entries(PAGE_TEXT)) {
    for (const scheme of schemes) {
      it(`${name} meets WCAG AA in ${scheme} mode`, () => {
        // 16px tab labels / 16px error body — normal text, so the 4.5:1 floor.
        expect(checkText(pair[scheme], THEME[scheme].bg, 16)).toMatchObject({ passes: true });
      });
    }
  }

  for (const scheme of schemes) {
    it(`muted "inherit" text meets WCAG AA in ${scheme} mode`, () => {
      // color: inherit + opacity — the adaptive default, dimmed. Checked
      // composited, because 0.75 alpha is a real contrast cost.
      const px = 12.8; // the smallest site using it: 0.8rem
      expect(
        checkText(adaptiveText(scheme, MUTED_PAGE_OPACITY), THEME[scheme].bg, px),
      ).toMatchObject({ passes: true });
    });
  }

  it('rejects the colours that shipped this bug', () => {
    // Negative controls: the three measured failures, plus the `red` that was
    // below AA in BOTH themes. If any of these starts passing, the surfaces or
    // the floor have drifted and every assertion above is worthless.
    const dark = THEME.dark.bg;
    expect(checkText('#4b5563', dark, 16).passes).toBe(false); // inactive tab, 2.05:1
    expect(checkText('#2563eb', dark, 16).passes).toBe(false); // active tab, 3.00:1
    expect(checkText('#666666', dark, 12.8).passes).toBe(false); // muted hint, 2.70:1
    expect(checkText('#ff0000', dark, 16).passes).toBe(false); // plain `red`, 3.88:1
    expect(checkText('#ff0000', THEME.light.bg, 16).passes).toBe(false); // ...and 4.00:1
  });

  it('rejects a muted opacity that is too low to read', () => {
    // The opacity is the whole guard for `color: inherit` text — pin that a
    // slacker value would be caught.
    expect(checkText(adaptiveText('light', 0.5), THEME.light.bg, 12.8).passes).toBe(false);
  });
});
