/**
 * WCAG contrast maths, for asserting colour pairs in a unit test.
 *
 * ─── Why this exists ────────────────────────────────────────────────────────
 * The project rule (.claude/rules/frontend.md) is a MANUAL two-theme browser
 * pass, and it has now failed twice in the same way: a `getComputedStyle` sweep
 * can only measure elements that are **in the DOM at that moment**. The
 * pantry-staples "Saved" notice renders only after a successful save, so a sweep
 * of the open settings modal reported "nothing below AA" while a 3.29:1 string
 * sat one interaction away. A snapshot of one state was reported as coverage of
 * all states.
 *
 * Asserting the DECLARED colour pairs closes that gap, because a constant does
 * not have to be on screen to be checked. It does not replace the browser pass
 * — only the browser knows what actually composites over what — but it catches
 * the case the browser pass structurally cannot see.
 *
 * jsdom computes no colours, so this deliberately takes plain hex strings and
 * does the arithmetic itself rather than going through getComputedStyle.
 *
 * ─── Closing half of findInlineColorPairs' blind spot ───────────────────────
 * {@link findInlineColorPairs} only sees a style object that declares a
 * background AND a colour together, and says so in its own doc comment. The
 * other half of the codebase declares only a FOREGROUND and inherits whatever
 * surface it lands on. That is precisely what shipped the MealPlanner dark-mode
 * bug: #4b5563 and #666666 are comfortable on white and 2.05:1 / 2.70:1 on the
 * `#242424` index.css paints in dark mode — invisible to the pair scan, because
 * neither line names a background.
 *
 * Widening that scan to pair EVERY bare foreground against both theme surfaces
 * does not work: the surface is a property of the ANCESTOR, not the line, and
 * the ~19 `#666` sites here mostly sit inside modals and cards that pin their
 * own light background, where the colour is right. All of them would fail and
 * the guard would be switched off within a week.
 *
 * So the foreground-only colours that genuinely sit on the ADAPTIVE page
 * background are named as constants (constants/theme.ts) and checked against
 * both surfaces via {@link THEME}. Same trade as the section above: a constant
 * does not have to be on screen — or on a known parent — to be checked.
 */

import type { ThemeName } from "../constants/theme";

/** `#rrggbb` → `[r, g, b]` (0-255). Throws on anything else, so a typo or an
 *  `rgba()`/named colour fails loudly instead of silently scoring as black. */
function rgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`contrast: expected #rrggbb, got ${JSON.stringify(hex)}`);
  const int = parseInt(m[1], 16);
  return [(int >> 16) & 255, (int >> 8) & 255, int & 255];
}

/** sRGB → relative luminance, per WCAG 2.x. */
function luminance(hex: string): number {
  const channels = rgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

/**
 * Composite `fg` at `alpha` over an opaque `bg`, returning the flattened hex.
 *
 * WCAG ratios are defined on opaque colours, so a translucent foreground —
 * `opacity: 0.75`, or index.css's own `rgba(255,255,255,0.87)` — has to be
 * flattened against what it sits on before it can be measured. Skipping this
 * step is how a semi-transparent colour gets "checked" at its nominal value and
 * scores far better than what the user actually sees.
 */
export function blend(fg: string, alpha: number, bg: string): string {
  const [f, b] = [rgb(fg), rgb(bg)];
  return (
    "#" +
    f
      .map((c, i) => Math.round(b[i] + (c - b[i]) * alpha))
      .map((c) => c.toString(16).padStart(2, "0"))
      .join("")
  );
}

/**
 * The two surfaces index.css actually paints, and the adaptive text colour each
 * one carries. `:root` is DARK by default and only flips light under
 * `@media (prefers-color-scheme: light)` — pinned against the stylesheet by
 * contrast.test.ts so these can't drift out of sync with it.
 */
export const THEME = {
  light: { bg: "#ffffff", fg: "#213547", fgAlpha: 1 },
  dark: { bg: "#242424", fg: "#ffffff", fgAlpha: 0.87 },
} as const satisfies Record<ThemeName, { bg: string; fg: string; fgAlpha: number }>;

/**
 * The colour that `color: "inherit"` resolves to on the page background, in the
 * given theme — optionally dimmed by an extra `opacity`.
 *
 * This is the theme-correct alternative to a hardcoded grey: it dims whatever
 * the adaptive default already is, so it cannot invert when the scheme flips.
 * The opacity still has to be checked, though — it is a real contrast lever.
 */
export function adaptiveText(scheme: ThemeName, opacity = 1): string {
  const t = THEME[scheme];
  return blend(t.fg, t.fgAlpha * opacity, t.bg);
}

/** Contrast ratio between two hex colours. Symmetric — role does not matter. */
export function contrastRatio(a: string, b: string): number {
  const [l1, l2] = [luminance(a), luminance(b)];
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

/**
 * The AA floor for text at `px` and `weight`.
 *
 * 3:1 applies only to LARGE text — 24px, or 18.66px when bold. Getting this
 * wrong in the lenient direction is how a failing colour passes a check, so the
 * threshold is derived rather than assumed.
 */
export function wcagAAFloor(px: number, weight = 400): 3 | 4.5 {
  return px >= 24 || (px >= 18.66 && weight >= 700) ? 3 : 4.5;
}

/** Assertion-friendly: `{ ratio, floor, passes }` for a text colour on a surface. */
export function checkText(
  fg: string,
  bg: string,
  px: number,
  weight = 400,
): { ratio: number; floor: number; passes: boolean } {
  const ratio = Math.round(contrastRatio(fg, bg) * 100) / 100;
  const floor = wcagAAFloor(px, weight);
  return { ratio, floor, passes: ratio >= floor };
}

/** The handful of CSS colour keywords this codebase actually uses inline. */
const NAMED: Record<string, string> = {
  white: '#ffffff',
  black: '#000000',
  red: '#ff0000',
  gray: '#808080',
  grey: '#808080',
};

/** Normalise `white` / `#fff` / `#ffffff` to `#rrggbb`, or null if unparseable. */
export function toHex(value: string): string | null {
  const v = value.trim().toLowerCase();
  if (NAMED[v]) return NAMED[v];
  if (/^#[0-9a-f]{3}$/.test(v)) return `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
  if (/^#[0-9a-f]{6}$/.test(v)) return v;
  return null;
}

export interface InlinePair {
  file: string;
  line: number;
  fg: string;
  bg: string;
  px: number;
  bold: boolean;
}

/**
 * The rendered px of a block's `fontSize`, following React's own rule.
 *
 * React appends `px` to a NUMERIC value, so `fontSize: 14` is 14px — but the
 * old parser had no unit branch for that and fell through to "must be rem",
 * scoring it 224px. Anything over 24px gets WCAG's large-text 3:1 floor
 * instead of 4.5:1, so every numerically-sized element in the codebase was
 * being graded on the lenient threshold. That is precisely how
 * admin/FeedbackPanel's Accept button held 3.30:1 even after the scan was
 * widened to see it: 14 became 224, 224 earned the 3:1 floor, and 3.30 cleared
 * it. A guard that silently upgrades text to "large" is worse than no guard,
 * because it reports green.
 */
export function fontSizePx(body: string): number {
  const m = /fontSize:\s*(?:"([^"]+)"|([0-9.]+))/.exec(body);
  if (!m) return 16; // the app's base size, when the element sets none
  if (m[2] !== undefined) return parseFloat(m[2]); // numeric -> React writes px
  const value = m[1].trim();
  const rem = /^([0-9.]+)\s*rem$/.exec(value);
  if (rem) return parseFloat(rem[1]) * 16;
  const px = /^([0-9.]+)\s*px$/.exec(value);
  if (px) return parseFloat(px[1]);
  const bare = /^[0-9.]+$/.exec(value);
  if (bare) return parseFloat(value); // "14" is still px, not rem
  // em / % / calc() / a variable: unknown. Assume the STRICTER floor rather
  // than guessing large, so an unparseable size can never buy the 3:1 bar.
  return 16;
}

/**
 * If a string literal starts at `i`, the index just past its closing quote;
 * otherwise `i` itself.
 *
 * Brace counting has to skip string contents for the same reason
 * {@link stripComments} tracks quote state: a brace inside a value —
 * `content: "{"`, a `url(data:…)` — is a character, not structure, and counting
 * it desyncs every block boundary after it. That desync would be SILENT, which
 * is the one failure mode this whole file exists to prevent. Not live in the
 * codebase today; closed by construction because the analogous `//`-inside-a-
 * string hole in stripComments was not, and had to be fixed twice.
 */
function skipString(src: string, i: number): number {
  const quote = src[i];
  if (quote !== '"' && quote !== "'" && quote !== '`') return i;
  for (let j = i + 1; j < src.length; j++) {
    if (src[j] === '\\') {
      j++;
      continue;
    }
    if (src[j] === quote) return j + 1;
  }
  return src.length; // unterminated — treat the rest as string, not structure
}

/** Index of the `}` matching the `{` at `open`, or -1. Quote-aware. */
function matchingBrace(src: string, open: number): number {
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const skipped = skipString(src, i);
    if (skipped !== i) {
      i = skipped - 1;
      continue;
    }
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) return i;
  }
  return -1;
}

/**
 * Every brace-balanced object literal in the file, as its OWN-LEVEL text —
 * nested objects blanked out, offsets preserved so line numbers stay honest.
 *
 * Own-level matters: a palette record like
 *   const STATUS_COLORS = { planned: { bg: "#e2e8f0", text: "#475569" }, … }
 * must yield each inner `{ bg, text }` as its own block. Reading the record as
 * one flat lump would pair `planned.bg` with `finished.text` and assert a
 * combination that never renders.
 */
function styleBlocks(src: string): { at: number; own: string }[] {
  const blocks: { at: number; own: string }[] = [];
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== '{') continue;
    const end = matchingBrace(src, i);
    if (end === -1) continue;
    let own = '';
    let depth = 0;
    for (let j = i + 1; j < end; j++) {
      // A quoted value is copied through whole — the caller reads those hexes —
      // but its braces must not move `depth`.
      const strEnd = skipString(src, j);
      if (strEnd !== j) {
        const literal = src.slice(j, Math.min(strEnd, end));
        own += depth === 0 ? literal : literal.replace(/[^\n]/g, ' ');
        j = Math.min(strEnd, end) - 1;
        continue;
      }
      const ch = src[j];
      if (ch === '{') depth++;
      // Blank nested content but keep length and newlines, so an offset inside
      // `own` still maps back onto the original source.
      own += depth === 0 ? ch : ch === '\n' ? '\n' : ' ';
      if (ch === '}') depth--;
    }
    blocks.push({ at: i + 1, own });
  }
  return blocks;
}

/**
 * Every style object declaring a background AND a text colour TOGETHER.
 *
 * ⚠️ BLIND SPOT, and it is the important half: a foreground declared without a
 * background beside it is invisible here, because this cannot know which
 * ancestor surface it will land on. The pantry-staples "Saved" notice was
 * exactly that shape and needed the constants test instead. The checks are
 * complementary and none is sufficient:
 *
 *   • this one  — catches a self-contained button/badge nobody has re-rendered
 *   • constants — catches a colour that only appears in one interaction state
 *   • the browser pass — the only one that knows what actually composites
 *
 * BLOCK-based, not line-based. It used to compare a background and a colour
 * only when they sat on the same physical line, which made every multi-line
 * `style={{ … }}` structurally invisible — and that is how admin/FeedbackPanel's
 * Accept button shipped `#ffffff` on `#16a34a` at 3.30:1, the very colour this
 * file keeps as a NEGATIVE CONTROL, on the control that moves real money.
 *
 * Reads the CSS names AND the shorthands palette records use — `bg` for the
 * background, `text` or `fg` for the foreground. Matching only the CSS names is
 * how PlanCalendar's `cooked` chip kept a 3.00:1 `#16a34a` through the two
 * separate sweeps that fixed that very colour in PantryStaples and PlanCatalog.
 * Each alternative is boundary-guarded so a longer identifier — `helperText:`,
 * `cardbg:` — cannot match by accident.
 */
export function findInlineColorPairs(source: string, file: string): InlinePair[] {
  const pairs: InlinePair[] = [];
  // Comments are stripped for the same reason findUncoloredControls strips
  // them: a hex quoted in prose ("#16a34a was 3.00:1 here") is documentation,
  // not a declaration, and this file is full of exactly that.
  const src = stripComments(source);
  const lineOf = (i: number) => src.slice(0, i).split('\n').length;

  for (const { at, own } of styleBlocks(src)) {
    const bgMatch = /(?:^|[^a-zA-Z])(?:background(?:Color)?|bg):\s*"([^"]+)"/i.exec(own);
    if (!bgMatch) continue;
    const bg = toHex(bgMatch[1]);
    if (!bg) continue;
    const rest = own.replace(bgMatch[0], '');
    const fgMatch = /(?:^|[^a-zA-Z])(?:color|text|fg):\s*"([^"]+)"/i.exec(rest);
    if (!fgMatch) continue;
    const fg = toHex(fgMatch[1]);
    if (!fg) continue;
    const px = fontSizePx(own);
    pairs.push({
      file,
      // The BACKGROUND's line, not the block's opening brace — that is the line
      // someone has to go and edit.
      line: lineOf(at + bgMatch.index),
      fg,
      bg,
      px,
      bold: /fontWeight:\s*"?(?:600|700|800|900|bold)/.test(own),
    });
  }
  return pairs;
}

export interface UncoloredControl {
  file: string;
  line: number;
  /** The background value that made the UA keyword visible. */
  background: string;
}

/**
 * Form controls that override their background but declare no `color`.
 *
 * This is a THIRD blind spot, distinct from the two above, and the nastiest
 * because the failing colour appears nowhere in the source. A `<button>` does
 * not inherit `color` from its ancestors — with none set it resolves to the UA
 * `buttontext` keyword, and `index.css` declares `color-scheme: light dark`,
 * so under a dark OS theme that keyword is WHITE. As long as the control also
 * keeps the UA's own background it stays self-consistent (index.css paints
 * buttons #1a1a1a in dark, and white-on-#1a1a1a is fine). Override the
 * background — to `none`, or to a fixed light value — and the pairing breaks:
 * the ancestor's surface shows through while the text stays UA-white.
 *
 * Three sites shipped this: MealPlanner's day-card toggle (1.03:1 on #fcfcfc),
 * AuthBar's ⚙️ (1.07:1 on #f0f8ff) and MealEditor's `smallBtn`, used by
 * "+ Add ingredient" and "+ Add step" (1:1 on #fff — literally invisible).
 * None of them is visible to `findInlineColorPairs`, because none declares a
 * foreground at all.
 *
 * Deliberately narrow: only CONTROLS, and only when they override the
 * background. Widening it to every element with a background and no colour
 * would flag ~30 legitimate overlay scrims, gradient bars and progress fills,
 * and the guard would be switched off within a week. The fix at every site is
 * `color: "inherit"` (or an explicit colour when the surface is pinned).
 */
/**
 * Blank out comments, keeping every other character at its original offset so
 * line numbers stay honest.
 *
 * String-aware ON PURPOSE, rather than a regex. A regex cannot know whether a
 * `//` is a comment or part of a value, and getting that wrong here fails in
 * the worst direction: blanking from a `//` inside `url(https://…)` also eats
 * the closing `}} />`, so the tag scan never terminates and the offending
 * control drops out of the results ENTIRELY. A guard that exists to catch
 * silent regressions must not have a silent hole of its own.
 *
 * A lookbehind for `://` was the first fix and was not enough — a
 * protocol-relative `url(//cdn.example.com/x.png)` has no colon and would slip
 * straight back through. Tracking quote state costs a dozen lines and closes
 * the class instead of the instance.
 *
 * String CONTENTS are preserved, not blanked: the caller reads the quoted
 * `background` / `color` values out of this same text.
 */
function stripComments(source: string): string {
  const src = source.replace(/\r\n/g, '\n');
  const blank = (s: string) => s.replace(/[^\n]/g, ' ');
  let out = '';
  let i = 0;
  let quote: string | null = null;
  while (i < src.length) {
    const c = src[i];
    if (quote) {
      // Keep escapes intact — blanking `\"` would end the string early.
      if (c === '\\' && i + 1 < src.length) {
        out += c + src[i + 1];
        i += 2;
        continue;
      }
      if (c === quote) quote = null;
      out += c;
      i++;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      quote = c;
      out += c;
      i++;
      continue;
    }
    if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      const stop = end === -1 ? src.length : end + 2;
      out += blank(src.slice(i, stop));
      i = stop;
      continue;
    }
    if (c === '/' && src[i + 1] === '/') {
      const nl = src.indexOf('\n', i);
      const stop = nl === -1 ? src.length : nl;
      out += blank(src.slice(i, stop));
      i = stop;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

export function findUncoloredControls(source: string, file: string): UncoloredControl[] {
  const out: UncoloredControl[] = [];
  // Prose about `<button>` is not markup — see stripComments for why this is
  // not a regex.
  const src = stripComments(source);

  /** Balanced-brace slice starting at the `{` at `open`. */
  const block = (open: number) => {
    const end = matchingBrace(src, open);
    return end === -1 ? '' : src.slice(open + 1, end);
  };
  const bgOf = (body: string) =>
    /(?:^|[^a-zA-Z])background(?:Color)?:\s*["'`]?([^,\n}"'`]+)/.exec(body)?.[1]?.trim() ?? null;
  const hasColor = (body: string) => /(?:^|[^a-zA-Z-])color:/.test(body);
  const lineOf = (i: number) => src.slice(0, i).split('\n').length;

  // Style consts, so `style={btn}` / `style={{ ...btn, … }}` resolve too.
  const consts = new Map<string, string>();
  for (const m of src.matchAll(/const\s+(\w+)(?::\s*[\w<>., ]+)?\s*=\s*\{/g)) {
    consts.set(m[1], block(src.indexOf('{', m.index + m[0].length - 1)));
  }

  for (const m of src.matchAll(/<(button|input|select|textarea)[\s>]/g)) {
    // The opening tag, brace-aware so an arrow function's `=>` can't end it.
    let tag = '';
    for (let i = m.index, depth = 0; i < src.length; i++) {
      if (src[i] === '{') depth++;
      else if (src[i] === '}') depth--;
      else if (src[i] === '>' && depth === 0) {
        tag = src.slice(m.index, i + 1);
        break;
      }
    }
    // Checkboxes and radios paint no text, so buttontext cannot bite them.
    if (/type=\{?["']?(checkbox|radio|hidden)/.test(tag)) continue;
    let body = tag;
    for (const ref of tag.matchAll(/style=\{(\w+)\}|\.\.\.(\w+)/g)) {
      body += '\n' + (consts.get(ref[1] ?? ref[2]) ?? '');
    }
    const bg = bgOf(body);
    if (bg && !hasColor(body)) out.push({ file, line: lineOf(m.index), background: bg });
  }
  return out;
}

export interface KeywordColor {
  file: string;
  line: number;
  keyword: string;
}

/**
 * Inline `color:` declarations written as a bare CSS colour keyword.
 *
 * `white` and `black` are allowed: they are unambiguous, and every use in this
 * codebase sits beside an explicit background, so `findInlineColorPairs`
 * already measures them. Every OTHER keyword is a problem — not because the
 * keyword is wrong, but because it is what gets typed when nobody is thinking
 * about the surface. `red` is #ff0000, which is 4.00:1 on white and 3.66:1 on
 * the slate panel ReceiptScanner pins; `green` is #008000 at 2.85:1. Both
 * shipped, and in ReceiptScanner's case the SAME FILE already rendered its
 * other error in a checked #f87171 — the inconsistency is the tell.
 *
 * Deliberately narrow: only `color`, only bare keywords, and it says which one.
 * A keyword paired with a background is still caught by the pair scan; this
 * catches the ones with no background to pair against, which that scan cannot
 * see by construction.
 */
export function findKeywordColors(source: string, file: string): KeywordColor[] {
  const ALLOWED = new Set(['white', 'black', 'inherit', 'transparent', 'currentcolor']);
  const out: KeywordColor[] = [];
  const src = stripComments(source);
  for (const m of src.matchAll(/(?:^|[^a-zA-Z-])color:\s*"([a-zA-Z]+)"/g)) {
    const keyword = m[1].toLowerCase();
    if (ALLOWED.has(keyword)) continue;
    out.push({ file, line: src.slice(0, m.index).split('\n').length, keyword: m[1] });
  }
  return out;
}
