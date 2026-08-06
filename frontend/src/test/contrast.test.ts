/// <reference types="node" />
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve, join, relative } from 'node:path';
import {
  contrastRatio,
  wcagAAFloor,
  checkText,
  findInlineColorPairs,
  findUncoloredControls,
  blend,
  adaptiveText,
  THEME,
} from './contrast';
import {
  SURFACE,
  NOTICE_OK_COLOR,
  NOTICE_ERROR_COLOR,
  MUTED_COLOR,
} from '../components/PantryStaples';
import { PAGE_TEXT, MUTED_PAGE_OPACITY, type ThemeName } from '../constants/theme';
import { AUTHBAR_SURFACE, LINK_ON_AUTHBAR } from '../components/AuthBar';
import {
  ON_DARK_SURFACE,
  ON_DARK_ROW_SURFACE,
  ON_DARK_TEXT,
  ON_DARK_MUTED,
  ON_DARK_ERROR,
} from '../components/Fridge';

/** Every non-test .tsx/.ts under a directory. */
function walkTsx(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return walkTsx(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\./.test(entry.name) ? [full] : [];
  });
}

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

describe('every inline background/foreground pair in the app', () => {
  // Five failing sites were sitting in shipped code — Register, Logout,
  // Regenerate, Confirm Plan and cook mode's Done — through THREE separate
  // manual browser passes over those very screens. A manual sweep measures
  // what is on screen at that moment and gets reported as coverage of the
  // component; this reads every declaration, whether or not anything rendered.
  const files = walkTsx(resolve(process.cwd(), 'src'));
  const pairs = files.flatMap((f) =>
    findInlineColorPairs(readFileSync(f, 'utf-8'), relative(process.cwd(), f)),
  );

  it('finds pairs to check at all', () => {
    // Guards the guard: a broken walk or regex would make the assertion below
    // pass over an empty list, which is the failure mode this whole file is
    // about. The floor is deliberately well BELOW the real count (22 across 88
    // files at the time of writing) — this asserts "the scan still works", not
    // "the palette has not changed", and a tight bound would just false-alarm
    // on any refactor that merges two styled elements.
    expect(pairs.length).toBeGreaterThan(10);
    expect(files.length).toBeGreaterThan(50);
  });

  it('all meet WCAG AA', () => {
    const failing = pairs
      .map((p) => ({ ...p, ...checkText(p.fg, p.bg, p.px, p.bold ? 700 : 400) }))
      .filter((p) => !p.passes)
      .map((p) => `${p.file}:${p.line} ${p.fg} on ${p.bg} = ${p.ratio}:1 (needs ${p.floor})`);
    expect(failing).toEqual([]);
  });
});

describe('form controls that override their background', () => {
  // The buttontext trap: a <button> takes the UA keyword rather than
  // inheriting, and `color-scheme: light dark` flips that keyword white under a
  // dark OS theme. Nothing in the source names the failing colour, so neither
  // the pair scan nor a constants check can see it — only this shape can.
  const files = walkTsx(resolve(process.cwd(), 'src'));
  const offenders = files.flatMap((f) =>
    findUncoloredControls(readFileSync(f, 'utf-8'), relative(process.cwd(), f)),
  );

  it('always declare a color', () => {
    expect(
      offenders.map((o) => `${o.file}:${o.line} background=${o.background} with no color`),
    ).toEqual([]);
  });

  it('detects the shape that shipped three times', () => {
    // Negative control. Without this, a broken regex would report an empty
    // offender list and the assertion above would pass for the wrong reason.
    const bad = `
      const smallBtn = { background: "none", border: "1px solid #ccc" };
      export function X() {
        return <div style={{ backgroundColor: "#fff" }}>
          <button type="button" style={smallBtn}>+ Add step</button>
          <button type="button" style={{ ...smallBtn, color: "#b91c1c" }}>x</button>
          <button type="button" style={{ padding: 4 }}>inherits the UA pairing</button>
          <input type="checkbox" style={{ background: "none" }} />
        </div>;
      }`;
    // Only the first button: the second declares a colour, the third keeps the
    // UA's own background (so it stays self-consistent), and a checkbox paints
    // no text.
    expect(findUncoloredControls(bad, 'x.tsx').map((o) => o.background)).toEqual(['none']);
  });

  it('does not count a <button> written inside a comment', () => {
    const prose = `// a <button style={{ background: "none" }}> does not inherit color\n`;
    expect(findUncoloredControls(prose, 'x.tsx')).toEqual([]);
  });

  it('does not mistake a URL inside a string for the start of a comment', () => {
    // A naive `//` stripper blanks the rest of the line from `https://`. That
    // takes the closing `}} />` with it, so the tag scan never terminates and
    // the control drops out of the results entirely — the offender is missed
    // SILENTLY, which is the one failure mode this guard exists to prevent.
    // The second assertion is therefore the discriminating one: under the naive
    // regex BOTH return [], so only "an offender is still found" catches it.
    const withColor = `<button style={{ background: "url(https://x.test/a.png)", color: "#111" }} />`;
    expect(findUncoloredControls(withColor, 'x.tsx')).toEqual([]);
    const withoutColor = `<button style={{ background: "url(https://x.test/a.png)" }} />`;
    expect(findUncoloredControls(withoutColor, 'x.tsx')).toHaveLength(1);
  });
});

describe('the AuthBar surface', () => {
  // Pinned #f0f8ff, so both halves are fixed and the check is exact. The old
  // #007bff link was 3.71:1 — under AA in BOTH themes, and invisible to the
  // pair scan because the background is declared 110 lines above the colour.
  it('keeps its link above AA', () => {
    expect(checkText(LINK_ON_AUTHBAR, AUTHBAR_SURFACE, 13.6)).toMatchObject({ passes: true });
  });

  it('rejects the blue that shipped', () => {
    expect(checkText('#007bff', AUTHBAR_SURFACE, 13.6).passes).toBe(false);
  });
});

describe('the fridge batch surface', () => {
  // Batch rows/cards pin #0f172a in BOTH themes, so — unlike PAGE_TEXT — their
  // foregrounds must NOT follow the scheme. They shipped with no `color` at
  // all, which meant the cells inherited the adaptive default and read #213547
  // on #0f172a (1.42:1) under a LIGHT OS theme: the mirror image of the dark
  // bug, and the reason a one-theme check keeps missing half of these.
  const cases: [string, string, number][] = [
    ['body', ON_DARK_TEXT, 16],
    ['muted', ON_DARK_MUTED, 13.6],
    ['use-soon badge', ON_DARK_ERROR, 11.2],
  ];
  // BOTH pinned slates: batch rows/cards use #0f172a, and the expanded summary
  // row sits one step lighter at #1e293b while sharing these same foregrounds.
  // Asserting only the darker one left the lighter pairing resting on a
  // hand-computed number in a code comment.
  const surfaces: [string, string][] = [
    ['batch', ON_DARK_SURFACE],
    ['expanded summary row', ON_DARK_ROW_SURFACE],
  ];
  for (const [surfaceName, surface] of surfaces) {
    for (const [name, color, px] of cases) {
      it(`${name} meets WCAG AA on the pinned ${surfaceName} surface`, () => {
        expect(checkText(color, surface, px)).toMatchObject({ passes: true });
      });
    }
  }

  it('rejects the adaptive light-theme default that these cells were inheriting', () => {
    expect(checkText(THEME.light.fg, ON_DARK_SURFACE, 16).passes).toBe(false);
    expect(checkText(THEME.light.fg, ON_DARK_ROW_SURFACE, 16).passes).toBe(false);
  });
});
