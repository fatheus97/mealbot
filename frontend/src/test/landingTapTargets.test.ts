/// <reference types="node" />
// Guards the landing page's small controls against the failure mode that put
// two of them under the WCAG 2.2 "Target Size (Minimum)" 24px floor: a button
// whose box is decided entirely by FONT METRICS the page does not control.
//
// #auth-close had no width/height and no font-family, so its width was the
// advance of U+00D7 in whatever font the UA picked — 25.9px on Arial, 1.9px of
// margin over the minimum. #auth-switch had `padding: 0` and `font: inherit`,
// so its height was one inherited line-box: 21.1px.
//
// jsdom does no layout — every rect is 0x0 and getComputedStyle resolves no
// cascade — so a render test cannot measure any of this. These assert the
// DECLARATIONS that keep each box font-independent; the sizes themselves are
// proved by getComputedStyle in the browser preview (ROADMAP U-8 tracks the
// Playwright setup that would automate it).
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const WCAG_MIN_PX = 24;

const html = readFileSync(resolve(process.cwd(), "index.html"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
const css = [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join("\n");

function ruleFor(selector: string): string {
  const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
  const match = rules.find((r) => r[1].split(",").some((s) => s.trim() === selector));
  if (!match) throw new Error(`no rule for ${selector} in index.html`);
  return match[2];
}

const px = (decls: string, prop: string): number | null => {
  const m = decls.match(new RegExp(`(?:^|[;{\\s])${prop}:\\s*([\\d.]+)px`));
  return m ? Number(m[1]) : null;
};

describe("landing page tap targets", () => {
  it("#auth-close declares its own box — its width must not come from a glyph advance", () => {
    const decls = ruleFor("#auth-close");
    // The × is a single character. Without explicit dimensions the button is
    // as wide as that glyph plus padding, in a font chosen by the UA.
    expect(px(decls, "width")).toBeGreaterThanOrEqual(WCAG_MIN_PX);
    expect(px(decls, "height")).toBeGreaterThanOrEqual(WCAG_MIN_PX);
    // Every other button on the page pins the page font; this one used to be
    // the exception, which is what made its size UA-dependent.
    expect(decls).toMatch(/font-family:\s*inherit/);
  });

  it("#auth-switch has padding — with none, its height is one inherited line box", () => {
    const decls = ruleFor(".auth-linkbtn");
    const padding = decls.match(/(?:^|[;{\s])padding:\s*([^;]+)/)?.[1].trim();
    expect(padding).toBeDefined();
    expect(padding).not.toBe("0");
    // The equal negative margin is what keeps the enlarged hit box from
    // reflowing the sentence the button sits in. Padding without it would push
    // the surrounding text apart.
    expect(decls).toMatch(/(?:^|[;{\s])margin:\s*-/);
  });

  it(".btn declares a line-height — <button> does not inherit body's", () => {
    // .btn is used on both <a> and <button>. The UA's `font: -webkit-small-control`
    // resets line-height to `normal` on form controls and a UA declaration beats
    // inheritance, so leaving it unset rendered the same class 3.6px shorter on
    // every button — including both submits.
    expect(ruleFor(".btn")).toMatch(/(?:^|[;{\s])line-height:\s*[\d.]/);
  });
});
