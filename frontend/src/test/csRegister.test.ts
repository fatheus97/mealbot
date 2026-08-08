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
const SPOKEN: { pattern: RegExp; instead: string; anywhere?: true }[] = [
  { pattern: /na rovinu/i, instead: "otevřeně — or restructure the sentence" },
  { pattern: /pořádně/i, instead: "pozorně / důkladně", anywhere: true },
  { pattern: /(^|[^\p{L}])teď([^\p{L}]|$)/iu, instead: "nyní / v současnosti" },
  { pattern: /dneska/i, instead: "dnes", anywhere: true },
  // `nem(á|ají)`, not `nemá(jí)?` — the singular carries an acute á while the
  // plural is a plain a plus jí, so the obvious-looking optional group can
  // never match "nemají". Caught by negative control: restoring the exact
  // phrase the owner flagged ("nemají žádnou cenu") failed nothing.
  { pattern: /nem(á|ají) (žádnou )?cenu/i, instead: "nemá smysl / je bezcenné" },
  { pattern: /(^|[^\p{L}])tohle([^\p{L}]|$)/iu, instead: "to / toto", anywhere: true },
  { pattern: /(^|[^\p{L}])věci([^\p{L}]|$)/iu, instead: "a concrete noun: údaje, položky, informace" },
  { pattern: /(^|[^\p{L}])hádat|hádali/iu, instead: "vést spor" },
  { pattern: /odstřihn/i, instead: "ukončit přístup / přerušit" },
  { pattern: /pokazil/i, instead: "došlo k chybě / nastal problém" },
  { pattern: /(^|[^\p{L}])prostě([^\p{L}]|$)/iu, instead: "drop it — it adds nothing", anywhere: true },
  { pattern: /(^|[^\p{L}])radši([^\p{L}]|$)/iu, instead: "raději", anywhere: true },
  { pattern: /(^|[^\p{L}])spíš([^\p{L}]|$)/iu, instead: "spíše", anywhere: true },
  { pattern: /(^|[^\p{L}])fakt([^\p{L}]|$)/iu, instead: "skutečně / opravdu", anywhere: true },
  { pattern: /(^|[^\p{L}])moc([^\p{L}]|$)/iu, instead: "příliš / velmi" },
  { pattern: /(^|[^\p{L}])dost([^\p{L}]|$)/iu, instead: "dostatečně" },
  { pattern: /(^|[^\p{L}])mrkn|koukn/iu, instead: "podívejte se / viz", anywhere: true },

  // ─── Reported by the owner, a native speaker, reading the shipped text ───
  // Each of these survived three machine passes and a meaning-focused review,
  // because none of them is a MEANING error — they are the kind of thing only
  // a native reader notices. They are listed by name so they cannot come back.
  //
  // `výmaz` is a registry word ("výmaz z obchodního rejstříku"). GDPR's Czech
  // does use "právo na výmaz" as a term of art, but in running prose about
  // deleting an account a Czech reader expects "smazání". The owner had
  // already corrected this once; a regeneration of the page silently reverted
  // it, which is also why these files now carry a HAND-EDITED SOURCE marker.
  { pattern: /(^|[^\p{L}])výmaz/iu, instead: "smazání / vymazání" },
  // A supermarket word, used here for a software feature.
  { pattern: /samoobsluž/i, instead: "say it plainly: „…si zatím nemůžete udělat sami“" },
  // English typographic habit; Czech uses „ “.
  { pattern: /"[^"]{3,40}"/, instead: "Czech quotation marks „…“" },
];

/**
 * Non-standard by MORPHOLOGY — wrong in any written Czech, marketing included.
 *
 * Flagged on the entry itself. The previous version derived this set by
 * testing whether a word appeared in `pattern.source`, which silently missed
 * `mrkni/koukni`: the pattern is /mrkn|koukn/, so `source.includes("mrkni")`
 * is false and that rule was never enforced on the marketing page at all.
 * A flag cannot drift from the pattern it sits on.
 */
const nonStandard = SPOKEN.filter((s) => s.anywhere);

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
  });

  // `prose()` reads BUILT HTML, which is the right source for everything a
  // visitor sees before JS runs — and blind to everything the landing bundle
  // WRITES at runtime. Button labels, validation messages and the
  // registration-open copy swaps all live in a TypeScript table that no build
  // output contains, so they had no register guard at all. The first run of
  // this block found one: "Tohle nevypadá jako platná e-mailová adresa",
  // shipped since the Czech landing page did.
  //
  // Marketing tier, deliberately: this copy is app voice, allowed to be warmer
  // than a contract. Only the forms that are non-standard by morphology apply.
  describe("runtime Czech copy (src/landing/copy.ts)", () => {
    /** The CS table only. The EN table above it is not Czech, and the shared
     *  interface between them is neither. */
    function czechTable(): string {
      const src = readFileSync(resolve(process.cwd(), "src/landing/copy.ts"), "utf-8");
      const start = src.indexOf("const CS: LandingCopy = {");
      expect(start, "src/landing/copy.ts no longer declares `const CS: LandingCopy`").toBeGreaterThan(-1);
      const end = src.indexOf("\n};", start);
      return src.slice(start, end);
    }

    it("uses no NON-STANDARD Czech", () => {
      const table = czechTable();
      const found = nonStandard
        .filter((s) => s.pattern.test(table))
        .map((s) => `${s.pattern} — use ${s.instead}`);
      expect(found).toEqual([]);
    });

    it("guards the guard: the slice really is the Czech table", () => {
      // A slice that silently came back empty — a renamed const, a reordered
      // file — would pass the assertion above by having nothing to match.
      const table = czechTable();
      expect(table.length).toBeGreaterThan(500);
      expect(table).toMatch(/[ěščřžýáíéůú]/);
      expect(table).not.toContain("const EN: LandingCopy");
    });
  });

  describe.skipIf(!hasBuild)("punctuation and voice", () => {
    it("does not punctuate Czech like English", () => {
      // The owner's first complaint. English uses the em-dash constantly as a
      // dramatic aside; the translation kept EVERY one, so both Czech pages
      // carried exactly as many as their English twins — 39 between them.
      // Czech reaches for a comma, a colon, parentheses, or two sentences.
      //
      // Zero, not "fewer": once the parenthetical-aside habit is gone there is
      // nothing left in these two documents that wants a dash, and a threshold
      // would just be a number to argue with later. If a genuine need ever
      // appears, changing this test is the right way to make that case.
      for (const page of LEGAL) {
        const dashes = (prose(page).match(/—/g) ?? []).length;
        expect(dashes, `${page} uses an em-dash in Czech prose`).toBe(0);
      }
      // Guards the guard: the English pages still use them heavily, so a
      // stripping bug that emptied `prose()` would show up here as a zero.
      const en = readFileSync(resolve(process.cwd(), "dist/terms.html"), "utf-8");
      const enProse = (en.match(/<body>([\s\S]*?)<\/body>/)?.[1] ?? "").replace(/<[^>]+>/g, " ");
      expect((enProse.match(/—/g) ?? []).length).toBeGreaterThan(10);
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
