/// <reference types="node" />
// Enforces the liability guardrail as a build-time check, not just a review
// convention (docs/landing-page-plan.md — "Liability guardrails (enforced,
// not just advisory)"). A future edit to the marketing copy that drops the
// disclaimer or reintroduces a forbidden endorsement/medical phrase should
// fail the build, not just hope someone notices in review.
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const distIndexPath = resolve(process.cwd(), "dist/index.html");
const hasBuiltOutput = existsSync(distIndexPath);

// The exact wording shipped on the DietarySelector chip UI
// (frontend/src/components/DietarySelector.tsx) — reused verbatim here so
// the landing page's promise matches what the product actually does.
const VERBATIM_DISCLAIMER =
  "Recipes are screened against your selected allergens and their common derivatives — this is a helper, not a guarantee. Always check product labels yourself.";

// Specific compound CLAIMS, not bare words (a bare "safe" would false-positive
// on legitimate uses like "safety-focused") — see docs/landing-page-plan.md's
// liability guardrails for the exact list.
const FORBIDDEN_PHRASES: RegExp[] = [
  /safe\s+for\s+(your|any)\s+allergy/i,
  /allergen-free/i,
  /hypoallergenic/i,
  /clinically\s+approved/i,
  /clinically\s+tested/i,
  /doctor-recommended/i,
  /medically\s+approved/i,
  /\bprescribed\b/i,
  /\b(cures|treats|prevents)\b/i,
];

describe("landing body copy (built dist/index.html)", () => {
  it("dist/index.html exists (run `npm run build` first)", () => {
    expect(hasBuiltOutput).toBe(true);
  });

  describe.skipIf(!hasBuiltOutput)("liability + CTA markup", () => {
    const html = readFileSync(distIndexPath, "utf-8");
    const body = html.match(/<body>([\s\S]*?)<\/body>/)?.[1] ?? "";

    it("carries the verbatim DietarySelector disclaimer", () => {
      // Collapse whitespace before comparing — the source hand-wraps this
      // sentence across lines for readability, which a browser (and a
      // reader) collapses to the same continuous text; a literal multi-line
      // match would fail on source formatting that has zero effect on what
      // actually renders.
      const normalized = body.replace(/\s+/g, " ").trim();
      expect(normalized).toContain(VERBATIM_DISCLAIMER);
    });

    it("matches zero forbidden endorsement/medical-advice phrases", () => {
      for (const pattern of FORBIDDEN_PHRASES) {
        expect(body).not.toMatch(pattern);
      }
    });

    it("names all 14 EU allergens", () => {
      const allergens = [
        "Gluten",
        "Crustaceans",
        "Eggs",
        "Fish",
        "Peanuts",
        "Soy",
        "Milk",
        "Tree nuts",
        "Celery",
        "Mustard",
        "Sesame",
        "Sulphites",
        "Lupin",
        "Molluscs",
      ];
      for (const allergen of allergens) {
        expect(body).toContain(allergen);
      }
    });

    it("never renders a live Sign up CTA that would 403 while registration is closed", () => {
      expect(body.toLowerCase()).not.toMatch(/>\s*sign up\s*</);
    });

    it("has the CTA baseline: mailto Request access + Log in to /app, in a reserved container", () => {
      expect(body).toContain('id="cta-box"');
      expect(body).toContain('id="cta-primary"');
      // While registration is closed the primary CTA scrolls to the request
      // form rather than opening a mail client — and it must be a real
      // in-page anchor so it works with JS disabled.
      expect(body).toMatch(/id="cta-primary"[^>]*href="#access"/);
      expect(body).toContain('id="access-form"');
      expect(body).toContain('id="cta-login"');
      expect(body).toMatch(/id="cta-login"[^>]*href="\/app"/);
    });

    it("the demo CTA is reserved (present, invisible) by default — not removed from the flow", () => {
      // A plain `hidden` attribute (display:none) would change how many
      // boxes flex-wrap lays out the moment the enhancement script reveals
      // it, resizing #cta-box — this is the CLS bug the visibility-based
      // .cta-reserved class exists to avoid. Assert the button stays IN the
      // markup (present) and carries the reserved class (invisible), not
      // that it's absent.
      expect(body).toMatch(/id="cta-demo"[^>]*class="[^"]*\bcta-reserved\b/);
    });

    it("mounts a different JS bundle than the SPA (app.html) — not the shared old entry", () => {
      // Vite rewrites <script src> to a hashed dist/assets/... path at build
      // time, so the SOURCE path ("/src/landing/main.ts") never appears in
      // built output — compare against app.html's bundle instead, which is
      // the actual thing this test needs to prove: the landing no longer
      // shares the SPA's entry module.
      const indexScript = html.match(/<script type="module"[^>]*src="([^"]+)"/)?.[1];
      expect(indexScript).toBeTruthy();
      expect(existsSync(resolve(process.cwd(), "dist", indexScript!.replace(/^\//, "")))).toBe(true);

      const appHtmlPath = resolve(process.cwd(), "dist/app.html");
      expect(existsSync(appHtmlPath)).toBe(true);
      const appHtml = readFileSync(appHtmlPath, "utf-8");
      const appScript = appHtml.match(/<script type="module"[^>]*src="([^"]+)"/)?.[1];
      expect(appScript).toBeTruthy();

      expect(indexScript).not.toBe(appScript);
    });

    it("references no third-party hosts in the body (CSP: img-src/connect-src 'self')", () => {
      const externalHostAttr = /(?:href|src)="https?:\/\/(?!trymealbot\.com)[^"]+"/;
      expect(body).not.toMatch(externalHostAttr);
    });
  });
});
