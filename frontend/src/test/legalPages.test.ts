/// <reference types="node" />
// The four legal pages — English and Czech editions of the Privacy Policy and
// the Terms — and the invariants that must hold ACROSS a language boundary.
//
// Both editions are equally authoritative (terms §13). That is the whole
// reason this file is strict: a divergence between them is not a typo, it is
// two different contracts, and the one the user reads is the one that binds.
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

interface LegalPage {
  dist: string;
  url: string;
  locale: "en" | "cs";
  /** The other edition of the SAME document. */
  peer: string;
}

const ORIGIN = "https://trymealbot.com";

const PAGES: LegalPage[] = [
  { dist: "dist/privacy.html", url: `${ORIGIN}/privacy`, locale: "en", peer: `${ORIGIN}/cs/privacy` },
  { dist: "dist/cs/privacy.html", url: `${ORIGIN}/cs/privacy`, locale: "cs", peer: `${ORIGIN}/privacy` },
  { dist: "dist/terms.html", url: `${ORIGIN}/terms`, locale: "en", peer: `${ORIGIN}/cs/terms` },
  { dist: "dist/cs/terms.html", url: `${ORIGIN}/cs/terms`, locale: "cs", peer: `${ORIGIN}/terms` },
];

const read = (p: string) => readFileSync(resolve(process.cwd(), p), "utf-8");
const hasBuild = PAGES.every((p) => existsSync(resolve(process.cwd(), p.dist)));

/** Czech compound safety CLAIMS. Compound, never bare words — a bare "bezpečn"
 *  false-positives on "bezpečnostní", which the copy uses legitimately. */
const FORBIDDEN_CS: RegExp[] = [
  /bezpečné?\s+pro\s+(vaši|jakoukoli|vaše)/i,
  /bez\s+alergenů/i,
  /hypoalergenn/i,
  /klinicky\s+(ověřen|testován|schválen)/i,
  /lékařsky\s+schválen/i,
  /\bzaručujeme\b/i,
  /\bgarantujeme\b/i,
];

it("all four legal pages are built (run `npm run build` first)", () => {
  // Unconditional, like every other dist-reading suite here: a missing build
  // must be a loud failure, not a file that silently reports zero tests.
  expect(hasBuild).toBe(true);
});

describe.skipIf(!hasBuild)("legal pages", () => {
  const html = Object.fromEntries(PAGES.map((p) => [p.dist, read(p.dist)]));

  it("each declares its own language", () => {
    for (const p of PAGES) {
      expect(html[p.dist], p.dist).toContain(`<html lang="${p.locale}">`);
    }
  });

  it("each Czech edition has its OWN title and description", () => {
    // These shipped English on the first pass. The translators were told not
    // to touch the <head> — correct for canonical and hreflang, wrong for
    // these two, which are prose and are the first Czech text a reader ever
    // sees: the browser tab and the Google snippet. Nothing asserted on them,
    // so CI was green through it.
    const tag = (s: string, re: RegExp) => s.match(re)?.[1]?.trim() ?? "";
    const TITLE = /<title>([^<]+)<\/title>/;
    const DESC = /<meta\s+name="description"\s+content="([^"]+)"/s;

    for (const doc of ["privacy", "terms"] as const) {
      const en = html[`dist/${doc}.html`];
      const cs = html[`dist/cs/${doc}.html`];
      for (const [name, re] of [["title", TITLE], ["description", DESC]] as const) {
        expect(tag(en, re).length, `${doc} en ${name} is empty`).toBeGreaterThan(10);
        expect(tag(cs, re), `${doc} ${name} is still English`).not.toBe(tag(en, re));
        expect(tag(cs, re).length, `${doc} cs ${name} is empty`).toBeGreaterThan(10);
      }
    }
  });

  it("each is self-canonical", () => {
    // These pages had NO canonical before this change, while being
    // `index, follow` with /privacy.html and /terms.html live as duplicates of
    // the extensionless URLs. It also disambiguates the hreflang cluster: an
    // annotation naming a URL whose page does not claim that URL is
    // self-contradictory.
    for (const p of PAGES) {
      expect(html[p.dist], p.dist).toContain(`<link rel="canonical" href="${p.url}" />`);
    }
  });

  it("each names BOTH editions of its own document, and itself", () => {
    // Reciprocity, computed per document rather than globally: privacy must
    // point at privacy and terms at terms. Pointing the Czech terms at the
    // English PRIVACY page would still produce a syntactically valid pair of
    // tags — and a cluster Google throws away.
    for (const p of PAGES) {
      const alts = Object.fromEntries(
        [...html[p.dist].matchAll(/<link rel="alternate" hreflang="([^"]+)" href="([^"]+)"/g)].map(
          (m) => [m[1], m[2]],
        ),
      );
      const en = p.locale === "en" ? p.url : p.peer;
      const cs = p.locale === "cs" ? p.url : p.peer;
      expect(alts, p.dist).toEqual({ en, cs, "x-default": en });
    }
  });

  it("all four carry the SAME machine-readable version date", () => {
    // Equally authoritative editions of one agreement. Two dates would mean
    // two versions, and `terms_version` records only one.
    const dates = PAGES.map((p) => html[p.dist].match(/<time datetime="([^"]+)"/)?.[1]);
    expect(dates.every((d) => d && /^\d{4}-\d{2}-\d{2}$/.test(d)), `dates: ${dates}`).toBe(true);
    expect(new Set(dates).size, `dates: ${dates}`).toBe(1);
  });

  it("the Czech editions make no safety claim the English does not", () => {
    for (const p of PAGES.filter((x) => x.locale === "cs")) {
      for (const pattern of FORBIDDEN_CS) {
        expect(html[p.dist], `${p.dist} ${pattern}`).not.toMatch(pattern);
      }
    }
  });

  it("both privacy editions state what the AI providers may do with the data", () => {
    // Since 2026-11-01 a request can go to OpenAI as well as Google. These are
    // the sentences that make that acceptable to a reader: who receives the
    // content and not the identity, the processor role, the training ban, the
    // retention limits and the transfer safeguard. Pinned in BOTH editions: the parity test above
    // compares names and figures only, so a paragraph deleted from one edition
    // could otherwise go unnoticed. The 30 days hold because OpenAI requests
    // send store=false (backend/app/llm/client.py, _provider_kwargs).
    const ws = (s: string) => new RegExp(s.split(" ").join(String.raw`\s+`));
    const en = html["dist/privacy.html"];
    const cs = html["dist/cs/privacy.html"];
    for (const phrase of [
      "Google and OpenAI receive the content, not who you are",
      "Google and OpenAI act as our processors",
      "forbid both from using it to improve their products or train their models",
      "we have not opted in to sharing data with OpenAI",
      "OpenAI keeps that copy for up to 30 days",
      "Google keeps it for 55 days",
      "under the EU Standard Contractual Clauses",
    ]) {
      expect(en, phrase).toMatch(ws(phrase));
    }
    for (const phrase of [
      "Google i OpenAI dostávají obsah, ne to, kdo jste",
      "zpracovávají jako zpracovatelé",
      "zakazují používat tyto údaje ke zlepšování svých produktů nebo k trénování svých modelů",
      "Sdílení údajů se společností OpenAI jsme navíc nezapnuli",
      "OpenAI tuto kopii uchovává nejvýše 30 dní",
      "Google ji uchovává 55 dní",
      "na základě standardních smluvních doložek EU",
    ]) {
      expect(cs, phrase).toMatch(ws(phrase));
    }
  });

  it("both privacy editions state the legal basis, the consent and the right to object", () => {
    // GDPR Art. 13(1)(c) and Art. 9(2)(a): the policy named no legal basis at
    // all until 2026-11-01, and diet/allergy data needs explicit consent, which
    // the app now collects (app/services/health_consent.py). Art. 21(4) wants
    // the right to object brought to attention separately. The telemetry
    // sentence is a promise the code keeps (telemetry.record_generation strips
    // the fields), so it is pinned too. Same both-editions reason as above.
    const ws = (s: string) => new RegExp(s.split(" ").join(String.raw`\s+`));
    const en = html["dist/privacy.html"];
    const cs = html["dist/cs/privacy.html"];
    for (const phrase of [
      "Why we are allowed to use your data",
      "Your explicit consent",
      "you can withdraw your consent at any time in Settings",
      "Your right to object",
      "This copy leaves out your diets, allergies and ingredients to avoid",
    ]) {
      expect(en, phrase).toMatch(new RegExp(ws(phrase).source, "i"));
    }
    for (const phrase of [
      "Na jakém právním základě vaše údaje používáme",
      "Váš výslovný souhlas",
      "Souhlas můžete kdykoli odvolat v Nastavení",
      "Vaše právo vznést námitku",
      "Tato kopie neobsahuje vaše typy stravy, alergie ani suroviny, kterým se chcete vyhnout",
    ]) {
      expect(cs, phrase).toMatch(ws(phrase));
    }
  });

  it("both editions of the Terms carry the equal-authority clause", () => {
    // The clause is what makes shipping a translation safe at all: neither
    // version is subordinate, and a discrepancy resolves in the reader's
    // favour. A Czech edition without it would be a document of unstated
    // status; an English edition without it would contradict the Czech one.
    expect(html["dist/terms.html"]).toMatch(/equally\s+authoritative/i);
    expect(html["dist/terms.html"]).toMatch(/more favourable to you/i);
    expect(html["dist/cs/terms.html"]).toMatch(/stejně\s+závazné/i);
    expect(html["dist/cs/terms.html"]).toMatch(/příznivější/i);
  });

  it("every figure and proper noun survives translation", () => {
    // The check that actually protects the money and the parties. Compared as
    // sorted multisets so ORDER may differ (Czech word order does) while the
    // SET of facts may not.
    //
    // The decimal separator is normalized first: Czech writes 4,99 € where
    // English writes €4.99, and that reformatting is correct — freezing the
    // English format to keep this test simple would have sacrificed the copy
    // to the guard.
    const norm = (s: string) => s.replace(/(\d),(\d\d)\b/g, "$1.$2");
    const PINNED = [
      "Stripe", "Resend", "Hetzner", "Google", "Gemini", "GitHub", "OpenAI",
      "22059946", "info@trymealbot.com",
    ];

    for (const doc of ["privacy", "terms"] as const) {
      const en = norm(html[`dist/${doc}.html`]);
      const cs = norm(html[`dist/cs/${doc}.html`]);
      const body = (s: string) => s.match(/<body>([\s\S]*?)<\/body>/)?.[1] ?? "";

      // No word boundaries. Czech fuses a numeral into a compound adjective —
      // "10denní", "14denní" — where English hyphenates it as "10-day". With
      // \b the Czech forms yield no token at all, and this test reported the
      // withdrawal-waiver clause as missing its 14 and its 10 when the clause
      // was in fact translated correctly. The guard was wrong, not the text.
      const figures = (s: string) => (body(s).match(/\d+(?:\.\d+)?/g) ?? []).sort();
      expect(figures(cs), `${doc}: numeric figures differ`).toEqual(figures(en));

      for (const name of PINNED) {
        const count = (s: string) => body(s).split(name).length - 1;
        if (count(en) > 0) {
          expect(count(cs), `${doc}: "${name}" appears ${count(en)}× in en`).toBe(count(en));
        }
      }
    }
  });

  it("each Czech edition ships CSS byte-identical to its English original", () => {
    // The Czech pages are prose-only transforms, so their inline stylesheets
    // are copies. Forking one to fit a longer Czech string would make the two
    // editions of one agreement render differently, and nothing else would
    // notice. Line endings normalized — a raw compare passes in CI and fails
    // only on a Windows working tree.
    const css = (s: string) => (s.match(/<style>([\s\S]*?)<\/style>/)?.[1] ?? "").split("\r\n").join("\n");
    for (const doc of ["privacy", "terms"] as const) {
      expect(css(html[`dist/cs/${doc}.html`]), doc).toBe(css(html[`dist/${doc}.html`]));
      expect(css(html[`dist/${doc}.html`]).length, doc).toBeGreaterThan(500); // guards the guard
    }
  });

  it("the sitemap names both legal clusters with the same URLs as the tags", () => {
    // Found by a negative control: forcing a trailing-slash mismatch on
    // /cs/terms in sitemap.xml failed NOTHING. landingCs.test.ts owns the
    // landing cluster and deliberately asserts containment, so the two legal
    // clusters were covered by neither suite — a hand-edited file that nothing
    // read, which is exactly how the landing cluster's own mismatch got in.
    const sitemap = readFileSync(resolve(process.cwd(), "dist/sitemap.xml"), "utf-8");

    // Parsed per <url> BLOCK, not flattened. A flat file-wide list of
    // alternates passes when a cluster loses one, because the same annotation
    // still exists inside a sibling cluster — proven by negative control:
    // deleting the cs alternate from the /privacy block failed nothing until
    // this was scoped. Same shape as the count-vs-each mistake on the landing
    // page's consent links.
    const blocks = [...sitemap.matchAll(/<url>([\s\S]*?)<\/url>/g)].map((m) => m[1]);
    const byLoc = new Map(
      blocks.map((b) => [
        b.match(/<loc>([^<]+)<\/loc>/)?.[1] ?? "",
        [...b.matchAll(/hreflang="([^"]+)" href="([^"]+)"/g)].map((m) => `${m[1]} ${m[2]}`),
      ]),
    );
    expect(byLoc.size, "sitemap has duplicate or unparsable <url> blocks").toBe(blocks.length);

    for (const p of PAGES) {
      const alts = byLoc.get(p.url);
      expect(alts, `sitemap has no <url> block for ${p.url}`).toBeDefined();
      const en = p.locale === "en" ? p.url : p.peer;
      const cs = p.locale === "cs" ? p.url : p.peer;
      // Exact set, not containment: an EXTRA alternate in a cluster is as
      // broken as a missing one.
      expect([...(alts ?? [])].sort(), `sitemap cluster for ${p.url}`).toEqual(
        [`en ${en}`, `cs ${cs}`, `x-default ${en}`].sort(),
      );
    }
  });

  it("the Czech editions link within Czech, not back into English", () => {
    for (const doc of ["privacy", "terms"] as const) {
      const b = html[`dist/cs/${doc}.html`];
      // The cross-link between the two Czech documents, and the back link.
      expect(b).toMatch(/href="\/cs\/(privacy|terms)"/);
      // The one deliberate English link is the language switch, which names
      // its language with hreflang. Anything else is a slip back into English.
      const withoutSwitch = b.replace(`<a href="/${doc}" hreflang="en" lang="en">English</a>`, "");
      expect(withoutSwitch).not.toMatch(/href="\/(privacy|terms)"/);
      expect(b).toContain('href="/cs"');
    }
  });

  it("each edition offers a visible link to the other one", () => {
    // A visitor the server sent to the Czech edition must be able to get the
    // English one (and back): both are equally authoritative (terms §13).
    for (const doc of ["privacy", "terms"] as const) {
      expect(html[`dist/cs/${doc}.html`]).toContain(`<a href="/${doc}" hreflang="en" lang="en">English</a>`);
      expect(html[`dist/${doc}.html`]).toContain(`<a href="/cs/${doc}" hreflang="cs" lang="cs">Čeština</a>`);
    }
  });
});
