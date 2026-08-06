/// <reference types="node" />
// The Czech marketing landing (dist/cs/index.html), and the hreflang cluster
// that ties it to the English one.
//
// Reads the BUILT output for the same reason landingHead/landingBody do: the
// build is what nginx and a crawler actually serve, and reading it catches a
// Vite transform mangling a tag. Requires `npm run build` first.
//
// ─── Why the liability guard is repeated here, in Czech ─────────────────────
// landingBody.test.ts enforces the disclaimer and the forbidden-claims list on
// the English page ONLY. Without a Czech twin, the page that is legally the
// riskier of the two — the one aimed at consumers in the operator's own
// jurisdiction — would ship with that guardrail silently switched off.
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cs } from "../i18n/cs";

const distEn = resolve(process.cwd(), "dist/index.html");
const distCs = resolve(process.cwd(), "dist/cs/index.html");
const hasBuild = existsSync(distEn) && existsSync(distCs);

/** Czech compound CLAIMS, mirroring FORBIDDEN_PHRASES in landingBody.test.ts.
 *  Compound, never bare words — a bare "bezpečn" would false-positive on the
 *  legitimate "bezpečnostní položka" ("safety field") the copy uses on purpose. */
const FORBIDDEN_CS: RegExp[] = [
  /bezpečné?\s+pro\s+(vaši|jakoukoli|vaše)/i,
  /bez\s+alergenů/i,
  /hypoalergenn/i,
  /klinicky\s+(ověřen|testován|schválen)/i,
  /doporučeno\s+lékař/i,
  /lékařsky\s+schválen/i,
  /\bzaručujeme\b/i,
  /\bgarantujeme\b/i,
  /\b(léčí|vyléčí|předchází nemocem)\b/i,
];

describe("Czech landing page", () => {
  it("dist/cs/index.html exists (run `npm run build` first)", () => {
    // Asserted unconditionally, like its English sibling: a missing build must
    // be a loud failure, not a file that silently reports zero tests.
    expect(hasBuild).toBe(true);
  });

  describe.skipIf(!hasBuild)("content", () => {
    const html = readFileSync(distCs, "utf-8");
    const body = html.match(/<body>([\s\S]*?)<\/body>/)?.[1] ?? "";
    const normalized = body.replace(/\s+/g, " ").trim();

    it("declares itself as Czech", () => {
      // The landing bundle reads exactly this attribute to pick its runtime
      // copy (src/landing/copy.ts), so it is behaviour, not just metadata.
      expect(html).toMatch(/<html lang="cs">/);
    });

    it("carries the verbatim Czech DietarySelector disclaimer", () => {
      // Pinned against the SPA's own dictionary rather than a copy of the
      // sentence: the visitor meets this exact line again on the allergen
      // chips after signing up, and the two drifting apart is the failure.
      const disclaimer = cs["diet.screeningDisclaimer"];
      // Guards the guard. A renamed key would make `disclaimer` undefined, and
      // an assertion written even slightly more forgivingly (`?? ""`) would
      // then pass against a page with no disclaimer at all.
      expect(disclaimer).toMatch(/pomůcka, ne záruka/);
      expect(normalized).toContain(disclaimer);
    });

    it("matches zero forbidden Czech endorsement/medical-advice phrases", () => {
      for (const pattern of FORBIDDEN_CS) {
        expect(body).not.toMatch(pattern);
      }
    });

    it("names all 14 allergens using the app's own Czech labels", () => {
      // Same words as the product UI. A translator "improving" one of these in
      // isolation would make the marketing page and the app disagree about
      // what a user is declaring, on the one list where that matters most.
      const labels = [
        cs["allergen.cereals_with_gluten"],
        cs["allergen.crustaceans"],
        cs["allergen.eggs"],
        cs["allergen.fish"],
        cs["allergen.peanuts"],
        cs["allergen.soybeans"],
        cs["allergen.milk"],
        cs["allergen.tree_nuts"],
        cs["allergen.celery"],
        cs["allergen.mustard"],
        cs["allergen.sesame"],
        cs["allergen.sulphites"],
        cs["allergen.lupin"],
        cs["allergen.molluscs"],
      ];
      expect(labels).toHaveLength(14);
      for (const label of labels) {
        expect(normalized).toContain(`<span class="chip">${label}</span>`.replace(/<[^>]+>/g, ""));
      }
    });

    it("names the regulation the Czech way", () => {
      expect(normalized).toContain("nařízení (EU) č. 1169/2011");
      expect(normalized).not.toContain("Regulation (EU) No 1169/2011");
    });

    it("points its legal links at the Czech pages", () => {
      // A Czech visitor sent to the English terms is the gap this whole page
      // exists to close.
      expect(body).toContain('href="/cs/privacy"');
      expect(body).toContain('href="/cs/terms"');
      expect(body).not.toContain('href="/privacy"');
      expect(body).not.toContain('href="/terms"');
    });

    it("formats prices the Czech way", () => {
      // Comma decimal, symbol after the number. "€4.99" is the English form
      // and reads as a typo to a Czech reader.
      expect(normalized).toContain("4,99 €");
      expect(normalized).toContain("2,99 €");
      expect(normalized).not.toContain("€4.99");
    });

    it("has no English marketing prose left in the body", () => {
      // The transform that built this page reports its own misses, but only
      // for rules it was GIVEN — a sentence nobody listed would pass silently.
      // This is the backstop: function words that cannot occur in Czech copy.
      const text = body
        .replace(/<[^>]+>/g, " ")
        .replace(/&[a-z]+;/g, " ")
        .replace(/\s+/g, " ");
      const english =
        /\b(the|your|with|every|recipe|allergens|please|about|which|account|advice)\b/gi;
      expect([...new Set(text.match(english) ?? [])]).toEqual([]);
    });
  });
});

describe("hreflang cluster", () => {
  describe.skipIf(!hasBuild)("reciprocity", () => {
    const pages = {
      en: readFileSync(distEn, "utf-8"),
      cs: readFileSync(distCs, "utf-8"),
    };

    function alternates(html: string): Record<string, string> {
      const out: Record<string, string> = {};
      for (const m of html.matchAll(
        /<link rel="alternate" hreflang="([^"]+)" href="([^"]+)"/g,
      )) {
        out[m[1]] = m[2];
      }
      return out;
    }

    // The failure this guards is not "a tag is missing" but "Google silently
    // discards the entire cluster". A one-sided annotation is not a partial
    // win — it is worth exactly nothing, and nothing about the served page
    // looks wrong, so only a test can see it.
    const EXPECTED = {
      en: "https://trymealbot.com/",
      cs: "https://trymealbot.com/cs",
      "x-default": "https://trymealbot.com/",
    };

    it("every page lists every locale, including itself", () => {
      for (const [name, html] of Object.entries(pages)) {
        expect(alternates(html), name).toEqual(EXPECTED);
      }
    });

    it("each page's canonical is the URL its own hreflang entry names", () => {
      // A canonical pointing somewhere other than the page's own alternate
      // entry makes the cluster self-contradictory: the tags claim /cs is the
      // Czech version while /cs itself claims to be a copy of something else.
      const canonicalOf = (html: string) =>
        html.match(/<link rel="canonical" href="([^"]+)"/)?.[1];
      expect(canonicalOf(pages.en)).toBe(EXPECTED.en);
      expect(canonicalOf(pages.cs)).toBe(EXPECTED.cs);
    });

    it("uses absolute URLs — a relative hreflang is silently ignored", () => {
      for (const html of Object.values(pages)) {
        for (const href of Object.values(alternates(html))) {
          expect(href).toMatch(/^https:\/\//);
        }
      }
    });
  });
});

describe("en/cs structural parity", () => {
  describe.skipIf(!hasBuild)("markup contract", () => {
    const en = readFileSync(distEn, "utf-8");
    const csHtml = readFileSync(distCs, "utf-8");

    const idsOf = (html: string) =>
      [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]).sort();

    it("both pages expose the same element ids", () => {
      // The landing bundle is ONE module served to both pages and finds its
      // DOM by id. An id translated or dropped on one page turns into a null
      // querySelector at runtime, on that page only — invisible to every test
      // that renders the other one.
      expect(idsOf(csHtml)).toEqual(idsOf(en));
    });

    it("both pages have the same number of FAQ entries", () => {
      const count = (html: string) => (html.match(/<details class="card">/g) ?? []).length;
      expect(count(csHtml)).toBe(count(en));
      expect(count(en)).toBeGreaterThan(0);
    });

    it("both pages have the same number of allergen chips", () => {
      const count = (html: string) => (html.match(/<span class="chip">/g) ?? []).length;
      expect(count(csHtml)).toBe(14);
      expect(count(en)).toBe(14);
    });

    it("each page offers a visible link to the other language", () => {
      // hreflang is machine-only. A visitor who lands on the wrong one has no
      // way across without this, and the sitemap/link tags give them nothing.
      expect(en).toContain('<a href="/cs" hreflang="cs" lang="cs">Čeština</a>');
      expect(csHtml).toContain('<a href="/" hreflang="en" lang="en">English</a>');
    });

    it("each page's FAQPage JSON-LD has one entry per on-page question", () => {
      // The structured data mirrors the visible FAQ. Adding a question to one
      // and not the other is a structured-data mismatch Google can penalise,
      // and it is the single easiest thing to forget on a page this long.
      for (const [name, html] of Object.entries({ en, cs: csHtml })) {
        const onPage = (html.match(/<summary>/g) ?? []).length;
        const inJsonLd = (html.match(/"@type": "Question"/g) ?? []).length;
        expect(inJsonLd, name).toBe(onPage);
      }
    });
  });
});
