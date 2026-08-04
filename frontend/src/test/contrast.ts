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
 */

/** sRGB → relative luminance, per WCAG 2.x. */
function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`contrast: expected #rrggbb, got ${JSON.stringify(hex)}`);
  const int = parseInt(m[1], 16);
  const channels = [(int >> 16) & 255, (int >> 8) & 255, int & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
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
 * Every inline style declaring a background AND a text colour on the SAME LINE.
 *
 * ⚠️ BLIND SPOT, and it is the important half: a foreground declared without a
 * background beside it is invisible here, because this cannot know which
 * ancestor surface it will land on. The pantry-staples "Saved" notice was
 * exactly that shape and needed the constants test instead. The two checks are
 * complementary and neither is sufficient:
 *
 *   • this one  — catches a self-contained button/badge nobody has re-rendered
 *   • constants — catches a colour that only appears in one interaction state
 *   • the browser pass — the only one that knows what actually composites
 *
 * Line-based rather than AST-based on purpose: the codebase writes these as
 * single-line `style={{ … }}` objects, and a parser would be a lot of machinery
 * to check a convention that a regex reads directly.
 */
export function findInlineColorPairs(source: string, file: string): InlinePair[] {
  const pairs: InlinePair[] = [];
  source.replace(/\r\n/g, '\n').split('\n').forEach((line, i) => {
    const bgMatch = /background(?:Color)?:\s*"([^"]+)"/.exec(line);
    if (!bgMatch) return;
    const bg = toHex(bgMatch[1]);
    if (!bg) return;
    const rest = line.replace(bgMatch[0], '');
    const fgMatch = /(?:^|[^a-zA-Z])color:\s*"([^"]+)"/i.exec(rest);
    if (!fgMatch) return;
    const fg = toHex(fgMatch[1]);
    if (!fg) return;
    const sizeMatch = /fontSize:\s*"?([0-9.]+)(rem|px)?"?/.exec(line);
    const px = sizeMatch
      ? sizeMatch[2] === 'px'
        ? parseFloat(sizeMatch[1])
        : parseFloat(sizeMatch[1]) * 16
      : 16; // the app's base size, when the element does not set one
    pairs.push({
      file,
      line: i + 1,
      fg,
      bg,
      px,
      bold: /fontWeight:\s*"?(?:600|700|800|900|bold)/.test(line),
    });
  });
  return pairs;
}
