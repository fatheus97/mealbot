/// <reference types="node" />
// Mirrors landingHead.test.ts's approach (read the BUILT output, not the
// source template) for app.html — the SPA's own namespace since the
// landing-page split (docs/landing-page-plan.md). Distinct concern from
// landingHead.test.ts: this guards against app.html silently losing its
// noindex tag, or picking up index.html's marketing meta (canonical/OG/
// JSON-LD), which would be wrong for a page that must never be indexed.
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const distAppPath = resolve(process.cwd(), "dist/app.html");
const hasBuiltOutput = existsSync(distAppPath);

describe("app shell <head> (built dist/app.html)", () => {
  // Same rationale as landingHead.test.ts's precondition guard: nothing
  // enforces build-before-test ordering, so assert it unconditionally
  // rather than letting a missing build silently report 0 tests.
  it("dist/app.html exists (run `npm run build` first)", () => {
    expect(hasBuiltOutput).toBe(true);
  });

  describe.skipIf(!hasBuiltOutput)("head content", () => {
    const html = readFileSync(distAppPath, "utf-8");
    const head = html.match(/<head>([\s\S]*?)<\/head>/)?.[1] ?? "";

    it("is marked noindex — it must never compete with the landing page for indexing", () => {
      expect(head).toContain('<meta name="robots" content="noindex"');
    });

    it("does not carry index.html's marketing meta — that belongs on the landing page only", () => {
      expect(head).not.toContain('rel="canonical"');
      expect(head).not.toContain('property="og:');
      expect(head).not.toContain('name="twitter:');
      expect(head).not.toContain('application/ld+json');
    });

    it("mounts the SPA bundle, not the landing entry", () => {
      expect(html).toMatch(/<div id="root"><\/div>/);
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
