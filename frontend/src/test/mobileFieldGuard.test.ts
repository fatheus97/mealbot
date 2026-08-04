/// <reference types="node" />
// Guards the phone-breakpoint field rule in index.css, which is the app's only
// `!important`. It exists because iOS zooms the viewport (and does NOT zoom
// back out) when a focused input/select/textarea renders below 16px — a device
// behaviour, not a design preference. The app is 100% inline `style={}`, so
// without `!important` any component that pins its own font-size silently opts
// that one control out of the guard; a dozen already had.
//
// jsdom evaluates neither @media nor the author-vs-inline cascade, so a render
// test can't observe this. Asserting the declaration itself is the only check
// that fails when someone drops the `!important` or lowers the floor; the real
// proof is a getComputedStyle measurement at 375px in the browser preview.
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Strip comments first — the surrounding prose talks about `font-size` and
// would otherwise match before the real declaration does.
const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

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

describe("index.css phone-breakpoint field guard", () => {
  const phone = mediaBlock(css, "@media (max-width: 640px)");
  const rules = [...phone.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
  const fieldRule = rules.find((r) => /\bselect\b/.test(r[1]));

  it("has a rule covering input, select and textarea", () => {
    expect(fieldRule).toBeDefined();
    expect(fieldRule![1]).toMatch(/\binput\b/);
    expect(fieldRule![1]).toMatch(/\btextarea\b/);
    // Checkboxes and radios have no text to zoom and a 40px floor would
    // balloon them, so they are deliberately excluded.
    expect(fieldRule![1]).toContain('input:not([type="checkbox"]):not([type="radio"])');
  });

  it("pins font-size at or above the 16px iOS zoom threshold, with !important", () => {
    const decl = fieldRule![2].match(/font-size:\s*([\d.]+)px\s*(!important)?/);
    expect(decl).not.toBeNull();
    expect(Number(decl![1])).toBeGreaterThanOrEqual(16);
    expect(decl![2]).toBe("!important");
  });

  it("pins a 40px minimum tap target, with !important", () => {
    const decl = fieldRule![2].match(/min-height:\s*([\d.]+)px\s*(!important)?/);
    expect(decl).not.toBeNull();
    expect(Number(decl![1])).toBeGreaterThanOrEqual(40);
    expect(decl![2]).toBe("!important");
  });

  it("is the file's only !important — desktop sizes stay a component decision", () => {
    // Every `!important` in the file must live in this one rule. If a
    // specificity fight elsewhere starts reaching for it, that's a design
    // problem to solve in the component, not a second exception here.
    expect(css.match(/!important/g)?.length).toBe(fieldRule![2].match(/!important/g)?.length);
  });
});
