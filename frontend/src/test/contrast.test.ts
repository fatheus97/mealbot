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
  fontSizePx,
  findKeywordColors,
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
import { DISABLED_TEXT, DISABLED_SURFACE } from '../components/DayLayoutEditor';
import { FAVORITE_SAVED, FAVORITE_UNSAVED } from '../components/FavoriteStar';
import {
  OUT_OF_MONTH_SURFACE,
  OUT_OF_MONTH_DAY,
  IN_MONTH_DAY,
  TODAY_COLOR,
} from '../components/PlanCalendar';
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

  it('does not mistake a protocol-relative URL for the start of a comment', () => {
    // `//cdn…` has no colon, so the lookbehind that fixed `https://` would let
    // this straight back through. Same silent-miss shape, narrower trigger —
    // which is why the stripper tracks quote state instead of pattern-matching
    // the protocols it has been bitten by so far.
    const withColor = `<button style={{ background: "url(//cdn.test/a.png)", color: "#111" }} />`;
    expect(findUncoloredControls(withColor, 'x.tsx')).toEqual([]);
    const withoutColor = `<button style={{ background: "url(//cdn.test/a.png)" }} />`;
    expect(findUncoloredControls(withoutColor, 'x.tsx')).toHaveLength(1);
  });

  it('still strips a real comment that follows a string on the same line', () => {
    // The other direction: quote tracking must not make the stripper give up on
    // genuine trailing comments.
    const src = `const x = "a"; // <button style={{ background: "none" }} />\n`;
    expect(findUncoloredControls(src, 'x.tsx')).toEqual([]);
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

describe('the calendar month grid', () => {
  // Inside a modal that pins #fff, so both halves are fixed.
  const cases: [string, string, string][] = [
    ['in-month day number', IN_MONTH_DAY, '#ffffff'],
    ['out-of-month day number', OUT_OF_MONTH_DAY, OUT_OF_MONTH_SURFACE],
    ['today, in month', TODAY_COLOR, '#ffffff'],
    // `today` lands in an adjacent-month cell as soon as you page forward a
    // month, so it has to clear AA on the tinted surface too.
    ['today, adjacent month', TODAY_COLOR, OUT_OF_MONTH_SURFACE],
  ];
  for (const [name, fg, bg] of cases) {
    it(`${name} meets WCAG AA`, () => {
      expect(checkText(fg, bg, 11.52)).toMatchObject({ passes: true });
    });
  }

  it('rejects the dimmed values that shipped', () => {
    // Adjacent-month cells used to be de-emphasised with `opacity: 0.5` on the
    // CELL, which multiplies every descendant. These are the composited results
    // — the day number, and the status chips, which are enabled buttons whose
    // own colour pair the guard was still reporting at full strength.
    expect(checkText(blend('#374151', 0.5, '#ffffff'), '#fdfdfe', 11.52).passes).toBe(false);
    expect(checkText(blend('#1d4ed8', 0.5, '#ffffff'), '#fdfdfe', 10.88).passes).toBe(false);
    // No opacity rescues it: even 0.85 leaves `today` short.
    expect(checkText(blend(TODAY_COLOR, 0.85, '#ffffff'), '#fdfdfe', 11.52).passes).toBe(false);
  });
});

describe('findInlineColorPairs spellings', () => {
  // The scan is only as good as the property names it recognises. A palette
  // record spelled differently is invisible to it, and an invisible record is
  // exactly how the same #16a34a survived three separate sweeps.
  const pair = (src: string) => findInlineColorPairs(src, 'x.tsx').map((p) => `${p.fg}|${p.bg}`);

  it('reads the CSS names and both palette shorthands', () => {
    expect(pair(`<div style={{ backgroundColor: "#fff", color: "#111" }} />`)).toEqual(['#111111|#ffffff']);
    expect(pair(`<div style={{ background: "#fff", color: "#111" }} />`)).toEqual(['#111111|#ffffff']);
    // PlanCalendar / PlanCatalog spell it this way…
    expect(pair(`  cooked: { bg: "#dcfce7", text: "#166534" },`)).toEqual(['#166534|#dcfce7']);
    // …and the two admin StatusBadge maps spell it this way.
    expect(pair(`  open: { bg: "#dbeafe", fg: "#1d4ed8" },`)).toEqual(['#1d4ed8|#dbeafe']);
  });

  it('does not match a longer identifier that merely ends in a keyword', () => {
    // Both sides are boundary-guarded. Without it, `cardbg`/`helperText` would
    // be read as a colour pair and the scan would assert nonsense.
    expect(pair(`<div style={{ cardbg: "#fff", helperText: "#111" }} />`)).toEqual([]);
    expect(pair(`<div style={{ backgroundColor: "#fff", helperText: "#111" }} />`)).toEqual([]);
  });

  it('sees the admin palette records that the CSS-name-only regex missed', () => {
    // Guards the widening itself: if the alternation loses `fg`, these two files
    // go quiet again and `all meet WCAG AA` starts passing over nothing.
    const admin = ['src/components/admin/InvitePanel.tsx', 'src/components/admin/FeedbackPanel.tsx'];
    for (const rel of admin) {
      const found = findInlineColorPairs(readFileSync(resolve(process.cwd(), rel), 'utf-8'), rel);
      expect(found.length).toBeGreaterThan(0);
    }
  });
});

describe('disabled layout-editor controls', () => {
  // WCAG 1.4.3 exempts inactive controls, so none of this was a violation —
  // it is a deliberate house standard above the floor. The ↑/↓ arrows are
  // disabled at the ends of EVERY list (so they are always on screen), and the
  // at-max button carries real information rather than just a dead label.
  const surfaces: [string, string][] = [
    ['its own row', '#fafafa'],
    ["MealPlanner's day card", '#fcfcfc'],
    ['the Settings modal', '#ffffff'],
    ['the at-max fill', DISABLED_SURFACE],
  ];
  for (const [name, bg] of surfaces) {
    it(`disabled text meets WCAG AA on ${name}`, () => {
      expect(checkText(DISABLED_TEXT, bg, 14.4)).toMatchObject({ passes: true });
    });
  }

  it('still reads as clearly dimmer than an active control', () => {
    // A "fix" that darkens disabled text until it looks enabled trades one
    // usability bug for another, so pin the separation, not just the floor.
    const active = checkText('#374151', '#fafafa', 14.4).ratio;
    const inactive = checkText(DISABLED_TEXT, '#fafafa', 14.4).ratio;
    expect(inactive).toBeLessThan(active / 1.5);
  });

  it('rejects the greys that shipped', () => {
    expect(checkText('#9ca3af', '#fafafa', 14.4).passes).toBe(false); // arrows, 2.43:1
    expect(checkText('#9ca3af', '#f3f4f6', 14.4).passes).toBe(false); // at-max, 2.31:1
    // The obvious #f3f4f6 fill is why the at-max button needed a lighter one:
    // the shared grey lands at 4.39:1 on it, just under the floor.
    expect(checkText(DISABLED_TEXT, '#f3f4f6', 14.4).passes).toBe(false);
  });
});

describe('findInlineColorPairs sees multi-line blocks', () => {
  const pairs = (src: string) => findInlineColorPairs(src, 'x.tsx').map((p) => `${p.fg}|${p.bg}`);

  it('pairs a background and colour declared on DIFFERENT lines', () => {
    // The whole point. Line-based scanning made every multi-line style object
    // invisible, which is how FeedbackPanel's Accept button shipped 3.30:1.
    const multi = `const acceptBtn: CSSProperties = {
  padding: "0.5rem 0.9rem",
  background: "#16a34a",
  color: "#ffffff",
};`;
    expect(pairs(multi)).toEqual(['#ffffff|#16a34a']);
  });

  it('keeps each entry of a palette record separate', () => {
    // Own-level parsing: reading the record as one lump would pair planned.bg
    // with finished.text and assert a combination that never renders.
    const record = `const STATUS_COLORS = {
  planned: { bg: "#e2e8f0", text: "#475569" },
  finished: { bg: "#f3e8ff", text: "#7c3aed" },
};`;
    expect(pairs(record)).toEqual(['#475569|#e2e8f0', '#7c3aed|#f3e8ff']);
  });

  it('ignores a hex quoted in a comment', () => {
    // This file and the components are full of "#16a34a was 3.00:1" prose.
    const prose = `// background: "#16a34a" with color: "#ffffff" was 3.30:1
const ok = { background: "#15803d", color: "#ffffff" };`;
    expect(pairs(prose)).toEqual(['#ffffff|#15803d']);
  });

  it('reports the background line, not the block opening', () => {
    const multi = `const a = {\n  padding: 4,\n  background: "#15803d",\n  color: "#ffffff",\n};`;
    expect(findInlineColorPairs(multi, 'x.tsx')[0].line).toBe(3);
  });
});

describe('fontSizePx follows React, not a guess', () => {
  it('treats a NUMERIC fontSize as px', () => {
    // React appends px to numbers. The old parser had no numeric branch and
    // fell through to "must be rem", scoring `fontSize: 14` as 224px — which
    // bought it WCAG's large-text 3:1 floor and let 3.30:1 pass as a success.
    expect(fontSizePx('fontSize: 14')).toBe(14);
    expect(fontSizePx('fontSize: "14"')).toBe(14);
    expect(fontSizePx('fontSize: "14px"')).toBe(14);
  });

  it('still converts rem', () => {
    expect(fontSizePx('fontSize: "0.85rem"')).toBeCloseTo(13.6, 5);
    expect(fontSizePx('fontSize: "1rem"')).toBe(16);
  });

  it('assumes the STRICT floor for a size it cannot parse', () => {
    // em/%/calc/a variable are unknown. Guessing large would hand out the 3:1
    // bar for free, so an unparseable size falls back to the 16px body size.
    expect(fontSizePx('fontSize: "1.2em"')).toBe(16);
    expect(fontSizePx('fontSize: "calc(1rem + 2px)"')).toBe(16);
    expect(fontSizePx('fontSize: titleSize')).toBe(16);
    expect(fontSizePx('padding: 4')).toBe(16);
  });

  it('never lets a 14px control be graded as large text', () => {
    // The exact regression: 3.30:1 must fail at 14px bold (large text needs
    // >=18.66px when bold), and would have passed at the mis-parsed 224px.
    expect(checkText('#ffffff', '#16a34a', fontSizePx('fontSize: 14'), 700).passes).toBe(false);
    expect(checkText('#ffffff', '#16a34a', 224, 700).passes).toBe(true);
  });
});

describe('block parsing is quote-aware', () => {
  const pairs = (src: string) => findInlineColorPairs(src, 'x.tsx').map((p) => `${p.fg}|${p.bg}`);

  // Which of these three actually discriminates: ONLY the closing-brace one.
  // Removing skipString fails that test alone. An unbalanced `{` in a value
  // self-corrects, because every `{` position is independently tried as a block
  // start, so a later block re-syncs; a stray `}` closes a block early and there
  // is no second chance. The other two are regression cover, not controls —
  // saying so because a test that looks like a control but always passes is
  // worse than no test.
  it('does not let a closing brace inside a string end a block early', () => {
    // The load-bearing case. A `}` in a VALUE is a character, not structure;
    // counting it truncates the block and the pair silently vanishes — the one
    // failure mode this file exists to prevent. Same shape as the
    // `//`-inside-a-string hole that had to be fixed twice in stripComments.
    const src = `const a = { content: "}", background: "#15803d", color: "#ffffff" };`;
    expect(pairs(src)).toEqual(['#ffffff|#15803d']);
  });

  it('also tolerates an opening brace inside a string (self-correcting)', () => {
    const src = `const a = { content: "{", background: "#15803d", color: "#ffffff" };
const b = { background: "#dcfce7", color: "#166534" };`;
    expect(pairs(src)).toEqual(['#ffffff|#15803d', '#166534|#dcfce7']);
  });

  it('keeps escaped quotes from ending a value early', () => {
    const src = `const a = { title: "say \\"hi\\" {", background: "#15803d", color: "#ffffff" };`;
    expect(pairs(src)).toEqual(['#ffffff|#15803d']);
  });
});

describe('no bare CSS colour keywords', () => {
  // The pair scan can only measure a colour that has a background beside it.
  // A bare keyword with no background is invisible to it — and a keyword is
  // exactly what gets typed when nobody is thinking about the surface.
  const files = walkTsx(resolve(process.cwd(), 'src'));

  it('are not used for text anywhere', () => {
    const found = files.flatMap((f) =>
      findKeywordColors(readFileSync(f, 'utf-8'), relative(process.cwd(), f)),
    );
    expect(found.map((k) => `${k.file}:${k.line} color: "${k.keyword}"`)).toEqual([]);
  });

  it('allows the unambiguous ones, rejects the rest', () => {
    // white/black always sit beside an explicit background here, so the pair
    // scan already measures them; inherit/transparent name no colour at all.
    const ok = `<div style={{ background: "#2563eb", color: "white" }} />
      <p style={{ color: "inherit", opacity: 0.75 }} />`;
    expect(findKeywordColors(ok, 'x.tsx')).toEqual([]);
    const bad = `<p style={{ color: "red" }} /><p style={{ color: "green" }} />`;
    expect(findKeywordColors(bad, 'x.tsx').map((k) => k.keyword)).toEqual(['red', 'green']);
  });

  it('rejects the two that shipped', () => {
    // #ff0000 is 3.66:1 on ReceiptScanner's #1e293b panel and 4.00:1 on white;
    // #008000 is 2.85:1 on that panel. Neither clears the 4.5 floor.
    expect(checkText('#ff0000', '#1e293b', 16).passes).toBe(false);
    expect(checkText('#ff0000', '#ffffff', 13.6).passes).toBe(false);
    expect(checkText('#008000', '#1e293b', 16).passes).toBe(false);
  });

  it('does not flag a keyword written in a comment', () => {
    expect(findKeywordColors(`// color: "red" was 4.00:1 here\n`, 'x.tsx')).toEqual([]);
  });
});

describe('the scans accept both quote styles', () => {
  // The codebase writes double quotes today, so nothing here is live. Accepted
  // anyway: "the guard only matches the spelling that last bit you" is how
  // `bg`/`text`/`fg` and `https://`/`//cdn…` each needed a second round.
  it('finds a single-quoted pair', () => {
    const src = `const a = { background: '#15803d', color: '#ffffff' };`;
    expect(findInlineColorPairs(src, 'x.tsx').map((p) => `${p.fg}|${p.bg}`)).toEqual([
      '#ffffff|#15803d',
    ]);
  });

  it('flags a single-quoted bare keyword', () => {
    expect(findKeywordColors(`<p style={{ color: 'red' }} />`, 'x.tsx').map((k) => k.keyword)).toEqual(
      ['red'],
    );
  });
});

describe('the favourite star', () => {
  // An icon-only toggle: the glyph IS the control, so WCAG 1.4.11 wants 3:1.
  // It shipped at 1.41:1 unsaved and 2.06:1 saved, on the two PINNED light
  // surfaces it renders on. Only the unsaved state was ever on screen during a
  // sweep — the saved one is a click away, the classic one-state blind spot.
  const surfaces = ['#f9fafb', '#f9f9f9'];
  for (const bg of surfaces) {
    it(`both states clear AA on ${bg}`, () => {
      expect(checkText(FAVORITE_SAVED, bg, 22.4)).toMatchObject({ passes: true });
      expect(checkText(FAVORITE_UNSAVED, bg, 22.4)).toMatchObject({ passes: true });
    });
  }

  it('rejects the pair that shipped', () => {
    expect(checkText('#d1d5db', '#f9fafb', 22.4).passes).toBe(false); // unsaved, 1.41:1
    expect(checkText('#f59e0b', '#f9fafb', 22.4).passes).toBe(false); // saved, 2.06:1
  });

  it('does not rely on the two states differing from each other', () => {
    // They are 1.04:1 apart — essentially the same luminance. That is FINE only
    // because the glyph changes shape too; if someone ever unifies the glyph,
    // this assertion is the reminder that colour alone cannot carry the state.
    expect(contrastRatio(FAVORITE_SAVED, FAVORITE_UNSAVED)).toBeLessThan(1.5);
  });
});
