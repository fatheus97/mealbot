import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

/**
 * Guards the Terms of Service.
 *
 * Two classes of sentence are pinned here, for opposite reasons:
 *
 * 1. **Safety limits.** These are the disclosures most likely to be softened
 *    later — they make the product sound worse. Every one of them corresponds
 *    to a real gap in `allergen_screen.py`, so deleting the sentence without
 *    closing the gap turns an honest page into a misleading one.
 * 2. **Commercial terms.** A price or limit stated inaccurately is a false
 *    contract term.
 */

const DIST = resolve(import.meta.dirname, "../../dist/terms.html");
const DIST_INDEX = resolve(import.meta.dirname, "../../dist/index.html");
const built = existsSync(DIST);

// Unconditional, so the skipIf below can never silently report zero tests.
it("dist/terms.html exists (run `npm run build` first)", () => {
  expect(built).toBe(true);
});

describe.skipIf(!built)("terms of service (built dist/terms.html)", () => {
  const html = built ? readFileSync(DIST, "utf8") : "";

  describe("safety limits that must never be quietly dropped", () => {
    it("describes how a non-English recipe is actually screened", () => {
      // This test used to assert /English ingredient names only/ — the claim
      // the page made before #341, when the term lists were English and the
      // prompt wrote ingredient names in the user's language, so the screen
      // genuinely matched nothing for a non-English user.
      //
      // That stopped being true and the page did not follow. Since #341
      // `screenable_names` (allergen_screen.py:361-366) screens the
      // model-supplied `name_en` ALONGSIDE the localized name, and an
      // ingredient without one is reported UNSCREENABLE, which the caller
      // turns into reject-and-regenerate — fail-closed. The old wording
      // understated the protection, which is the safe direction, but it was
      // wrong in a live contract.
      //
      // So this now pins the two halves of the real behaviour and, below, the
      // limit that genuinely remains. Keeping the old assertion would have
      // made the test block its own correction.
      expect(html).toMatch(/the AI must also supply an English name for each ingredient/i);
      expect(html).toMatch(/cannot be checked at all[\s\S]{0,120}rather than showing it to you/i);
    });

    it("discloses that the screen is only as good as the AI's English naming", () => {
      // The limit that survives #341: `name_en` is the model's own output, so
      // a mistranslation there is a word our English term lists will never
      // match, and the recipe passes.
      expect(html).toMatch(/leans on the AI's own English naming/i);
      expect(html).toMatch(/only as good as that translation/i);
      // Also in the top warning box, which is the part a reader actually sees.
      expect(html).toMatch(/depends on <strong>the AI's own English naming<\/strong>/i);
    });

    it("discloses that sulphites have no deterministic screen", () => {
      // allergen_screen.py:264 drops SULPHITES from the screenable set.
      expect(html).toMatch(/Sulphites are not covered/i);
    });

    it("discloses the language limit on step checking", () => {
      // Steps ARE screened now, but with English terms against prose written in
      // the user's language — so on a non-English recipe the defence is the
      // prompt rule, not the check. Claiming steps are simply "checked" would
      // overstate it for exactly the users the i18n work was for.
      expect(html).toMatch(/Cooking steps are checked in English only/i);
      expect(html).toMatch(/never to use anything\s+in a step that isn't in the ingredient list/i);
    });

    it("states that edits are checked but not blocked", () => {
      // Warn-don't-block: withholding is right for OUR output, but an edit is
      // the user's own recipe and their own declared allergy.
      expect(html).toMatch(/Edits you make are checked, but not blocked/i);
      expect(html).toMatch(/we still save it/i);
      // The edit path has no name_en to screen against, so it matches English
      // names only. Claiming an unqualified "we tell you clearly" would be a
      // promise the code cannot keep for non-English users.
      expect(html).toMatch(/reads English ingredient names/i);
    });

    it("states what the baby-food check does AND cannot do", () => {
      // It now HAS a deterministic backstop, so the old "no automatic safety
      // check" line would understate it — but the limits are what keep the
      // claim honest, so both halves are pinned.
      expect(html).toMatch(/an automatic check behind it/i);
      expect(html).toMatch(/cannot tell whether a food was cut to a safe size/i);
      expect(html).toMatch(/stricter than UK guidance/i);
    });

    it("keeps the helper-not-a-guarantee framing", () => {
      expect(html).toMatch(/helper, not a guarantee/i);
      expect(html).toMatch(/check the actual product labels/i);
    });

    it("uses no forbidden safety claim", () => {
      // docs/dietary-reference.md Part 4: transparency, never endorsement.
      for (const banned of [
        "safe for your allergy",
        "allergy-safe",
        "allergen-free",
        "hypoallergenic",
        "clinically approved",
        "doctor-recommended",
        "guaranteed safe",
      ]) {
        expect(html.toLowerCase()).not.toContain(banned);
      }
    });

    it("does not certify halal or kosher", () => {
      // \s+ because the source HTML wraps this phrase across a line — matching
      // a literal single space here made the test fail on formatting, not on
      // meaning.
      expect(html).toMatch(/not\s+certification/i);
    });
  });

  describe("commercial terms match what the code does", () => {
    it("states both prices and defers to Stripe checkout as authoritative", () => {
      // The backend never knows the amount — it passes an env-configured Price
      // id to Stripe — so checkout has to be the stated source of truth.
      expect(html).toContain("€4.99");
      expect(html).toContain("€2.99");
      expect(html).toContain("€35.88");
      expect(html).toMatch(/checkout page always shows the exact, current figure/i);
    });

    it("states the trial length and that it renews automatically", () => {
      expect(html).toMatch(/10 days/);
      expect(html).toMatch(/renew automatically/i);
    });

    it("states one trial per person AND per card", () => {
      // Both gates exist in trial_guard.py; the card one can claw back a trial
      // mid-flight, so it has to be a stated term.
      expect(html).toMatch(/One free trial per person, and one per payment card/i);
    });

    it("discloses the fair-use generation cap", () => {
      // usage_budget.py: ~€2/month subscribers, ~€0.75 for a whole trial. Users
      // hit this and currently see only a generic error, so the terms are the
      // only place it is disclosed at all.
      expect(html).toMatch(/€2 of model usage per calendar month/i);
      expect(html).toMatch(/€0\.75 for the whole trial/i);
    });

    it("takes the withdrawal-waiver position the operator chose", () => {
      expect(html).toMatch(/lose the 14-day right of withdrawal/i);
      expect(html).toMatch(/does not affect your statutory rights/i);
    });

    it("makes no uptime or availability promise", () => {
      // There is no SLA anywhere in the codebase; the terms must not imply one.
      expect(html).toMatch(/do not promise any particular uptime/i);
    });

    it("states the real per-request ceilings", () => {
      expect(html).toMatch(/1–7 days per plan/);
      expect(html).toMatch(/1–10 people/);
    });
  });

  describe("identifies the operator", () => {
    it("carries no unfilled placeholders", () => {
      expect(html.match(/\[OPERATOR[^\]]*\]/g)).toBeNull();
    });

    it("names the contracting party and IČO", () => {
      expect(html).toContain("František Bláha");
      expect(html).toMatch(/IČO 22059946/);
      expect(html).toMatch(/mailto:info@trymealbot\.com/);
    });
  });

  describe("reachability and theme safety", () => {
    it("is linked from the landing page footer", () => {
      const index = readFileSync(DIST_INDEX, "utf8");
      expect(index).toMatch(/href="\/terms"/);
    });

    it("links to the privacy policy", () => {
      expect(html).toMatch(/href="\/privacy"/);
    });

    it("defines a light-scheme override for every custom property", () => {
      const dark = html.match(/:root\s*\{([^}]*)\}/)?.[1] ?? "";
      const light =
        html.match(/prefers-color-scheme:\s*light\s*\)\s*\{\s*:root\s*\{([^}]*)\}/)?.[1] ?? "";
      const names = (block: string) =>
        new Set([...block.matchAll(/(--[a-z-]+)\s*:/g)].map((m) => m[1]));
      const darkVars = names(dark);
      expect(darkVars.size).toBeGreaterThan(5);
      expect([...darkVars].filter((v) => !names(light).has(v))).toEqual([]);
    });

    it("keeps wide tables in their own scroll container", () => {
      expect(html).toMatch(/\.table-scroll\s*\{[^}]*overflow-x:\s*auto/);
    });
  });
});
