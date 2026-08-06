/// <reference types="node" />
// Guards the hero's responsive layout against the trap that disabled it for as
// long as the landing page has existed: its grid properties lived in a
// `style=""` attribute, and an inline declaration outranks every author rule,
// so the phone breakpoint could not reach them at ANY specificity. The hero
// stayed two-column on a 375px phone, squeezing the headline into a 223px
// column against a fixed 96px logo.
//
// Same trap .claude/rules/frontend.md documents for the SPA's inline styles —
// there it is unavoidable (the app is 100% `style={}`), here it was not.
//
// jsdom does no layout, so no test can measure the resulting columns. These
// assert the two structural facts a layout regression would have to break; the
// rendered geometry is proved by getComputedStyle in the browser preview.
import { describe, it, expect } from "vitest";
import { landingCss, landingHtml, mediaBlock, ruleFor } from "./landingCss";

const PHONE_QUERY = "@media (max-width: 640px)";

const css = landingCss();
const html = landingHtml();

describe("landing hero responsive layout", () => {
  it("keeps the hero grid's layout in the stylesheet, not on the element", () => {
    // The opening tag of the hero grid container. An inline `style` here is not
    // a style choice — it silently opts the element out of every media query.
    const openTag = html.match(/<div class="steps"[^>]*>/);
    expect(openTag).not.toBeNull();
    expect(openTag![0]).not.toMatch(/\sstyle=/);
  });

  it("declares the hero grid at both widths, so the phone rule has something to override", () => {
    // Desktop: two columns, headline beside the mark.
    expect(ruleFor(css, "#hero .steps")).toMatch(/grid-template-columns:/);
    // Phone: collapsed to one, which is the whole point of moving it here.
    const phone = mediaBlock(css, PHONE_QUERY);
    expect(ruleFor(phone, "#hero .steps")).toMatch(/grid-template-columns:\s*1fr\s*;/);
  });
});
