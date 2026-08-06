/// <reference types="node" />
// Shared parsing for the landing page's stylesheet, which lives in an inline
// <style> block rather than a .css file. Third copy of this was about to be
// written, so it lives here instead — the comment-stripping order in
// particular is easy to get wrong (it must run on the raw HTML, before the
// <style> content is extracted, or CSS prose mentioning a property name gets
// matched as a declaration).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** Every <style> block in index.html, comments stripped, concatenated.
 *  Concatenated rather than indexed because the page has a second block
 *  inside <noscript>. */
export function landingCss(file = "index.html"): string {
  const html = readFileSync(resolve(process.cwd(), file), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
  return [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join("\n");
}

/** The body of an at-rule, brace-matched — a regex can't handle nested braces. */
export function mediaBlock(css: string, query: string): string {
  const start = css.indexOf(query);
  if (start === -1) throw new Error(`missing ${query}`);
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i);
  }
  throw new Error(`unterminated ${query}`);
}

/** The declaration body of the rule whose selector list contains `selector`. */
export function ruleFor(css: string, selector: string): string {
  const match = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find((r) =>
    r[1].split(",").some((s) => s.trim() === selector),
  );
  if (!match) throw new Error(`no rule for ${selector}`);
  return match[2];
}

/** Raw markup, for asserting on attributes rather than declarations. */
export function landingHtml(file = "index.html"): string {
  return readFileSync(resolve(process.cwd(), file), "utf-8");
}
