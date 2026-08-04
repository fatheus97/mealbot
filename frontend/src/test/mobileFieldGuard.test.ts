/// <reference types="node" />
// Guards the phone-breakpoint field rule on BOTH stylesheets that render a form
// field. It exists because iOS zooms the viewport (and does NOT zoom back out)
// when a focused input/select/textarea renders below 16px — a device behaviour,
// not a design preference.
//
// The two builds are separate and neither inherits the other's CSS: app.html
// loads src/index.css, index.html carries its own inline <style> block. So the
// guard is asserted twice, with one difference:
//
//   src/index.css  — `!important`, because the React app is 100% inline
//                    `style={}` and a dozen components had silently pinned
//                    their own font-size straight through the rule (#365).
//   index.html     — NO `!important`. Nothing on that page carries an inline
//                    style, and the element-level selector already outranks the
//                    two container rules (.auth-field input, .access-form
//                    textarea) that happen to cover today's fields. Keeping
//                    index.css's the project's only one is deliberate.
//
// jsdom evaluates neither @media nor the author-vs-inline cascade, so a render
// test can't observe any of this. Asserting the declarations is the only check
// that fails when someone drops the floor; the real proof is a getComputedStyle
// measurement at 375px in the browser preview.
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const PHONE_QUERY = "@media (max-width: 640px)";

// Strip comments first — the surrounding prose talks about `font-size` and
// `!important` and would otherwise match before the real declarations do.
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "");

const read = (relative: string) => stripComments(readFileSync(resolve(process.cwd(), relative), "utf-8"));

// index.html has more than one <style> element (the second is inside <noscript>),
// so concatenate them all rather than guessing which one holds the rule.
const inlineStyles = (html: string) =>
  [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join("\n");

// Brace-match the @media body; a regex can't handle the nested rule braces.
function mediaBlock(source: string, query: string): string {
  const start = source.indexOf(query);
  if (start === -1) throw new Error(`missing ${query}`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return source.slice(open + 1, i);
  }
  throw new Error(`unterminated ${query}`);
}

function fieldRuleOf(css: string): RegExpMatchArray {
  const phone = mediaBlock(css, PHONE_QUERY);
  const rule = [...phone.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find((r) => /\bselect\b/.test(r[1]));
  if (!rule) throw new Error(`no input/select/textarea rule inside ${PHONE_QUERY}`);
  return rule;
}

// `important: true` means the declaration MUST carry !important; `false` means
// it must NOT. Both directions matter — see the header comment.
const SHEETS = [
  { name: "src/index.css (React app)", css: () => read("src/index.css"), important: true },
  { name: "index.html (static landing page)", css: () => inlineStyles(read("index.html")), important: false },
];

describe.each(SHEETS)("phone-breakpoint field guard — $name", ({ css: load, important }) => {
  const css = load();
  const fieldRule = fieldRuleOf(css);
  const [, selector, decls] = fieldRule;
  const bang = important ? "!important" : undefined;

  it("covers input, select and textarea", () => {
    expect(selector).toMatch(/\binput\b/);
    expect(selector).toMatch(/\bselect\b/);
    expect(selector).toMatch(/\btextarea\b/);
    // Checkboxes and radios have no text to zoom and a 40px floor would
    // balloon them, so they are deliberately excluded.
    expect(selector).toContain('input:not([type="checkbox"]):not([type="radio"])');
  });

  it("pins font-size at or above the 16px iOS zoom threshold", () => {
    const decl = decls.match(/font-size:\s*([\d.]+)px\s*(!important)?/);
    expect(decl).not.toBeNull();
    expect(Number(decl![1])).toBeGreaterThanOrEqual(16);
    expect(decl![2]).toBe(bang);
  });

  it("pins a 40px minimum tap target", () => {
    const decl = decls.match(/min-height:\s*([\d.]+)px\s*(!important)?/);
    expect(decl).not.toBeNull();
    expect(Number(decl![1])).toBeGreaterThanOrEqual(40);
    expect(decl![2]).toBe(bang);
  });

  it("holds the line on !important — index.css's is the project's only one", () => {
    // On index.css: every `!important` in the file must live in this one rule,
    // so a specificity fight elsewhere can't quietly add a second exception.
    // On the landing page: there must be none at all.
    expect(css.match(/!important/g)?.length ?? 0).toBe(decls.match(/!important/g)?.length ?? 0);
  });
});
