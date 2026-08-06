/// <reference types="node" />
// Every Czech page must be written in SPISOVNÁ ČEŠTINA — the formal written
// register — not in obecná čeština, the spoken one.
//
// ─── Why this needs a test at all ───────────────────────────────────────────
// The first Czech legal pages were accurate and unusable: correct meaning,
// correct figures, correct obligations, written in the register of a
// conversation. Czech has a far wider spoken/written gap than English, so
// translating deliberately-plain English literally lands colloquial — and
// nothing in a meaning-focused review notices, because the meaning is right.
//
// The owner caught it by reading. This is the mechanical version of that read.
//
// ─── What this is NOT ───────────────────────────────────────────────────────
// It is not a push toward legalese. The English is plain on purpose, admits
// its own limits bluntly, and the Czech should too. "Samoobslužné mazání účtu
// zatím není k dispozici." is blunt AND formal — exactly right. The banned
// list below is spoken-register vocabulary only; it says nothing about
// sentence length or directness, and `vy`/`my` address is deliberate and
// stays. Nothing here would pass if it demanded "Uživatel je povinen".
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const LEGAL = ["dist/cs/privacy.html", "dist/cs/terms.html"];
const MARKETING = ["dist/cs/index.html"];
const hasBuild = [...LEGAL, ...MARKETING].every((p) => existsSync(resolve(process.cwd(), p)));

/**
 * NOT every Czech surface wants the same register, and pretending otherwise
 * would make this guard wrong rather than strict.
 *
 * A toast that says "Tohle už jste nám poslali — díky, máme to." is warm and
 * correct for an app. The same sentence in a contract is not. So the strict
 * list below applies to the LEGAL pages; the marketing page gets only the
 * subset that is obecná čeština by MORPHOLOGY — forms like `radši` and
 * `dneska` that are non-standard in any written Czech, however friendly the
 * tone. Words like `teď`, `věci` and `moc` are perfectly standard and simply
 * too casual for a contract, so they are enforced there and nowhere else.
 *
 * Word-boundary anchored on non-letters so "dost" does not fire inside
 * "dostatečně" and "moc" does not fire inside "pomocí".
 */
const SPOKEN: { pattern: RegExp; instead: string }[] = [
  { pattern: /na rovinu/i, instead: "otevřeně — or restructure the sentence" },
  { pattern: /pořádně/i, instead: "pozorně / důkladně" },
  { pattern: /(^|[^\p{L}])teď([^\p{L}]|$)/iu, instead: "nyní / v současnosti" },
  { pattern: /dneska/i, instead: "dnes" },
  // `nem(á|ají)`, not `nemá(jí)?` — the singular carries an acute á while the
  // plural is a plain a plus jí, so the obvious-looking optional group can
  // never match "nemají". Caught by negative control: restoring the exact
  // phrase the owner flagged ("nemají žádnou cenu") failed nothing.
  { pattern: /nem(á|ají) (žádnou )?cenu/i, instead: "nemá smysl / je bezcenné" },
  { pattern: /(^|[^\p{L}])tohle([^\p{L}]|$)/iu, instead: "to / toto" },
  { pattern: /(^|[^\p{L}])věci([^\p{L}]|$)/iu, instead: "a concrete noun: údaje, položky, informace" },
  { pattern: /(^|[^\p{L}])hádat|hádali/iu, instead: "vést spor" },
  { pattern: /odstřihn/i, instead: "ukončit přístup / přerušit" },
  { pattern: /pokazil/i, instead: "došlo k chybě / nastal problém" },
  { pattern: /(^|[^\p{L}])prostě([^\p{L}]|$)/iu, instead: "drop it — it adds nothing" },
  { pattern: /(^|[^\p{L}])radši([^\p{L}]|$)/iu, instead: "raději" },
  { pattern: /(^|[^\p{L}])spíš([^\p{L}]|$)/iu, instead: "spíše" },
  { pattern: /(^|[^\p{L}])fakt([^\p{L}]|$)/iu, instead: "skutečně / opravdu" },
  { pattern: /(^|[^\p{L}])moc([^\p{L}]|$)/iu, instead: "příliš / velmi" },
  { pattern: /(^|[^\p{L}])dost([^\p{L}]|$)/iu, instead: "dostatečně" },
  { pattern: /(^|[^\p{L}])mrkn|koukn/iu, instead: "podívejte se / viz" },
];

/** Non-standard by morphology — wrong in ANY written Czech, marketing included. */
const NONSTANDARD_ANYWHERE = new Set([
  "pořádně", "dneska", "tohle", "prostě", "radši", "spíš", "fakt", "mrkni/koukni",
]);
const nonStandard = SPOKEN.filter((s) =>
  [...NONSTANDARD_ANYWHERE].some((w) => s.instead.length > 0 && s.pattern.source.includes(w.split("/")[0])),
);

/** Visible prose only — a marker inside a class name or a URL is not read. */
function prose(page: string): string {
  const html = readFileSync(resolve(process.cwd(), page), "utf-8");
  return (html.match(/<body>([\s\S]*?)<\/body>/)?.[1] ?? "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");
}

describe("Czech pages are written in formal Czech", () => {
  it("the Czech pages are built (run `npm run build` first)", () => {
    expect(hasBuild).toBe(true);
  });

  describe.skipIf(!hasBuild)("register", () => {
    for (const page of LEGAL) {
      it(`${page} uses no spoken-register vocabulary at all`, () => {
        const text = prose(page);
        const found = SPOKEN.filter((s) => s.pattern.test(text)).map(
          (s) => `${s.pattern} — use ${s.instead}`,
        );
        expect(found).toEqual([]);
      });
    }

    for (const page of MARKETING) {
      it(`${page} uses no NON-STANDARD Czech (marketing may still be warm)`, () => {
        // Deliberately the smaller list. Marketing copy is allowed to be
        // friendlier than a contract; it is not allowed to be ungrammatical.
        const text = prose(page);
        const found = nonStandard.filter((s) => s.pattern.test(text)).map(
          (s) => `${s.pattern} — use ${s.instead}`,
        );
        expect(found).toEqual([]);
      });
    }

    it("guards the guard: the two lists are non-empty and the strict one is bigger", () => {
      expect(nonStandard.length).toBeGreaterThan(4);
      expect(SPOKEN.length).toBeGreaterThan(nonStandard.length);
    });

    it("still addresses the reader directly, rather than as a third party", () => {
      // Guards the guard, from the opposite side: the fix for colloquial Czech
      // is NOT to retreat into third-person legalese. If a future edit turns
      // "vy" into "Uživatel je povinen", the document has lost the voice its
      // English original was written in.
      const terms = readFileSync(resolve(process.cwd(), "dist/cs/terms.html"), "utf-8");
      expect(terms).toMatch(/\bvašeho|\bvaše|\bvám\b|\bvy\b/i);
      expect(terms).not.toMatch(/Uživatel je povinen/i);
    });
  });
});
