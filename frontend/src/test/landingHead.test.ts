/// <reference types="node" />
// This file inspects the build OUTPUT via Node's fs/path, not browser APIs.
// It runs under Node regardless of vitest.config.ts's jsdom `environment`
// (that only controls whether `window`/`document` exist) — but tsconfig.app.json
// (which covers all of src/, incl. this file) intentionally omits "node" from
// its types, since the rest of src/ is browser code. The reference above scopes
// Node globals to just this file instead of widening the whole app's type surface.
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// Reads the BUILT output (dist/index.html), not the source template — the
// build is what a crawler/social-unfurl bot and nginx actually serve, and
// reading it catches a Vite transform silently mangling a tag. Requires
// `npm run build` to have already run: true in CI (the frontend-build job
// runs `npm run build` then `npm test` in the same job); locally, run
// `npm run build` before `vitest run` — see docs/landing-page-plan.md.
const distIndexPath = resolve(process.cwd(), "dist/index.html");
const hasBuiltOutput = existsSync(distIndexPath);

describe("landing <head> (built dist/index.html)", () => {
  // Nothing enforces build-before-test ordering here — `npm test` is plain
  // `vitest run` with no pretest step, so this only holds today because
  // ci.yml happens to run `npm run build` right before `npm test`. Assert
  // the precondition itself, unconditionally, so a missing build is a loud
  // failure rather than the rest of this file silently reporting 0 tests.
  it("dist/index.html exists (run `npm run build` first)", () => {
    expect(hasBuiltOutput).toBe(true);
  });

  describe.skipIf(!hasBuiltOutput)("head content", () => {
    const html = readFileSync(distIndexPath, "utf-8");
    const head = html.match(/<head>([\s\S]*?)<\/head>/)?.[1] ?? "";

    it("has a real title, not the Vite scaffold placeholder", () => {
      expect(html).toMatch(/<title>[^<]{10,70}<\/title>/);
      expect(html).not.toContain("mealbot-frontend");
    });

    it("has a meta description of a healthy length for search snippets", () => {
      // [^>]* (not [\s\S]*?) so this can't accidentally span past the tag into
      // unrelated markup; attributes may be reordered/multi-line by hand-authoring
      // or a future Vite transform, so don't assume name= immediately precedes content=.
      const match = head.match(/<meta[^>]*\bname="description"[^>]*\bcontent="([^"]+)"/);
      expect(match).not.toBeNull();
      expect(match![1].length).toBeGreaterThan(50);
      expect(match![1].length).toBeLessThan(165);
    });

    it("has a canonical link pointing at the production origin", () => {
      expect(head).toContain('<link rel="canonical" href="https://trymealbot.com/"');
    });

    it("has Open Graph and Twitter card tags", () => {
      expect(head).toContain('property="og:type"');
      expect(head).toContain('property="og:title"');
      expect(head).toContain('property="og:description"');
      expect(head).toContain('property="og:url"');
      expect(head).toContain('name="twitter:card"');
      expect(head).toContain('name="twitter:title"');
    });

    it("has valid JSON-LD for Organization + SoftwareApplication + FAQPage with no price/offers", () => {
      const match = head.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
      expect(match).not.toBeNull();
      const data = JSON.parse(match![1]);
      const graph = data["@graph"] as Array<{ "@type": string }>;
      const types = graph.map((n) => n["@type"]);
      expect(types).toContain("Organization");
      expect(types).toContain("SoftwareApplication");
      // FAQPage should mirror the on-page FAQ (see landingBody.test.ts for the
      // visible copy) — at least as many questions as the FAQ section renders.
      const faqPage = graph.find((n) => n["@type"] === "FAQPage") as
        | { mainEntity: Array<{ "@type": string }> }
        | undefined;
      expect(faqPage).toBeDefined();
      expect(faqPage!.mainEntity.length).toBeGreaterThanOrEqual(5);
      // Price is deliberately omitted from structured data — Stripe checkout is
      // the authoritative source for the live figure, and a hardcoded price
      // here would silently go stale. Guard against it creeping back in.
      expect(head).not.toMatch(/"(price|offers)"\s*:/i);
    });

    // CSP compliance guard: nginx enforces script-src/style-src/font-src/
    // img-src 'self' (+ data:), so nothing in <head> may reference a
    // third-party host. This fails the build the instant anyone hotlinks a
    // CDN font/script/image/analytics beacon.
    it("references no third-party hosts in <head>", () => {
      const externalHostAttr = /(?:href|src|content)="https?:\/\/(?!trymealbot\.com)[^"]+"/;
      expect(head).not.toMatch(externalHostAttr);
    });

    it("every self-hosted asset referenced in <head> exists in the build output", () => {
      const assetPaths = [...head.matchAll(/(?:href|src)="\/([^"]+\.(?:svg|ico|png|webmanifest|json))"/g)].map(
        (m) => m[1],
      );
      expect(assetPaths.length).toBeGreaterThan(0);
      for (const asset of assetPaths) {
        expect(existsSync(resolve(process.cwd(), "dist", asset))).toBe(true);
      }
    });
  });
});
