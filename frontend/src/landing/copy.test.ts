import { describe, it, expect, afterEach } from "vitest";
import { landingLocale, landingCopy, type LandingCopy } from "./copy";

const EN_KEYS = Object.keys(landingCopy("en")) as (keyof LandingCopy)[];

function setLang(value: string | null) {
  if (value === null) document.documentElement.removeAttribute("lang");
  else document.documentElement.setAttribute("lang", value);
}

afterEach(() => setLang(null));

describe("landingLocale", () => {
  it.each([
    ["cs", "cs"],
    ["cs-CZ", "cs"],
    ["CS", "cs"],
    ["en", "en"],
    ["en-GB", "en"],
    ["de", "en"],
    ["", "en"],
  ])("lang=%o resolves to %o", (lang, expected) => {
    setLang(lang);
    expect(landingLocale()).toBe(expected);
  });

  it("falls back to English when the attribute is missing entirely", () => {
    // The failure mode has to be benign: a page that forgets `lang` renders
    // exactly what it renders today rather than throwing at module load.
    setLang(null);
    expect(landingLocale()).toBe("en");
  });

  it("reads the attribute at CALL time, not at module load", () => {
    // `copy.ts` is imported before any page markup exists in a test, and the
    // real bundle is a module shared by both HTML entry points. Caching the
    // locale at import would pin the whole bundle to whichever page loaded
    // first — which, being one bundle, is both of them.
    setLang("cs");
    expect(landingCopy().authLoginTitle).toBe("Přihlásit se");
    setLang("en");
    expect(landingCopy().authLoginTitle).toBe("Log in");
  });
});

describe("the two copy tables", () => {
  it("define exactly the same keys", () => {
    expect(Object.keys(landingCopy("cs")).sort()).toEqual([...EN_KEYS].sort());
    expect(EN_KEYS.length).toBeGreaterThan(20); // guards the guard
  });

  it("has no Czech value left identical to its English one", () => {
    // A table half-filled by copy-paste passes every key-set check above.
    // Nothing here is a loanword or a symbol, so identity means "untranslated".
    const en = landingCopy("en");
    const cs = landingCopy("cs");
    const identical = EN_KEYS.filter(
      (k) => typeof en[k] === "string" && en[k] === cs[k],
    );
    expect(identical).toEqual([]);
  });

  it("has no blank value in either table", () => {
    for (const locale of ["en", "cs"] as const) {
      const table = landingCopy(locale);
      for (const key of EN_KEYS) {
        const value = table[key];
        if (typeof value === "string") expect(value.trim(), `${locale}/${key}`).not.toBe("");
      }
    }
  });

  it("renders the interpolating entries in both languages", () => {
    // The only two entries that are functions. Czech uses the genitive plural
    // "znaků", which is correct for every bound of 5 or more — see the note on
    // `passwordTooShort` in copy.ts.
    expect(landingCopy("en").passwordTooShort(8)).toContain("8");
    expect(landingCopy("cs").passwordTooShort(8)).toBe("Heslo musí mít alespoň 8 znaků.");
    expect(landingCopy("cs").passwordTooLong(72)).toBe("Heslo musí mít nejvýše 72 znaků.");
  });

  it("keeps the consent sentence as ONE Czech string", () => {
    // "Souhlas s" governs the instrumental case, so the document names are
    // inflected — Obchodní podmínky becomes Obchodními podmínkami. Assembling
    // this sentence from the nominative link labels used in the footer would
    // produce a grammatically wrong sentence, which is why it is not built
    // from parts.
    expect(landingCopy("cs").authNeedTerms).toContain("Obchodními podmínkami");
    expect(landingCopy("cs").authNeedTerms).toContain(
      "Zásadami ochrany osobních údajů",
    );
  });
});
