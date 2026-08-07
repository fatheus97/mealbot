/// <reference types="node" />
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { formatDate, legalHref, localeTags } from "./localeFormat";
import { UI_LOCALES } from "../store/useLocaleStore";

describe("localeTags", () => {
  it("prefers a browser tag whose language matches the app locale", () => {
    // en-GB survives under `en`, so a British user keeps "7 Aug 2026".
    expect(localeTags("en", ["en-GB", "fr-FR"])).toEqual(["en-GB", "en"]);
  });

  it("ignores browser tags in another language", () => {
    // THE BUG THIS FILE EXISTS FOR: a Czech UI on an English browser used to
    // render English month names, because the call passed `undefined` and Intl
    // fell back to navigator.language. `en-GB` must not survive under `cs`.
    expect(localeTags("cs", ["en-GB", "en"])).toEqual(["cs"]);
  });

  it("matches case-insensitively and on the primary subtag only", () => {
    expect(localeTags("cs", ["CS-CZ"])).toEqual(["CS-CZ", "cs"]);
  });

  it("falls back to the bare locale when the browser offers nothing", () => {
    expect(localeTags("cs", [])).toEqual(["cs"]);
  });
});

describe("formatDate", () => {
  // Node's full-icu build backs these; the CI image is the same node:26 as the
  // container this suite runs in.
  it("renders month names in the app locale, not the browser's", () => {
    const en = formatDate("2026-08-07T00:00:00Z", "en");
    const cs = formatDate("2026-08-07T00:00:00Z", "cs");
    expect(en).toMatch(/Aug/);
    // Czech abbreviates August as "srp"/"srpna" depending on ICU version, so
    // assert on the DIFFERENCE rather than pinning a spelling that a node
    // upgrade could legitimately change.
    expect(cs).not.toEqual(en);
    expect(cs).not.toMatch(/Aug/);
  });

  it("returns an empty string for null and for an unparseable date", () => {
    expect(formatDate(null, "cs")).toBe("");
    expect(formatDate("not-a-date", "cs")).toBe("");
  });
});

describe("legalHref", () => {
  it("sends a Czech user to the Czech contract", () => {
    // The two editions are equally authoritative (#396), and the Czech one is
    // what actually binds a Czech consumer — so the paywall must not link the
    // English text to someone reading a Czech UI.
    expect(legalHref("cs", "terms")).toBe("/cs/terms");
    expect(legalHref("cs", "privacy")).toBe("/cs/privacy");
  });

  it("leaves English on the unprefixed paths", () => {
    expect(legalHref("en", "terms")).toBe("/terms");
    expect(legalHref("en", "privacy")).toBe("/privacy");
  });

  // The guard the allowlist's docstring promises, in BOTH directions. Either
  // mismatch is invisible to the rest of the suite — the SPA never navigates to
  // a legal page, so no render test can follow the href — and both land on the
  // one screen where money changes hands.
  const viteConfig = () =>
    readFileSync(resolve(import.meta.dirname, "../../vite.config.ts"), "utf-8");
  const isBuilt = (config: string, entry: string) =>
    config.includes(`'${entry}'`) || config.includes(`"${entry}"`);

  it("only points at pages the build actually emits", () => {
    // Allowlisted → the page exists. Catches a locale added to the allowlist
    // whose pages were never added to the Vite build: a link to a 404.
    const config = viteConfig();
    for (const locale of UI_LOCALES) {
      for (const doc of ["terms", "privacy"] as const) {
        const entry = `${legalHref(locale, doc).replace(/^\//, "")}.html`;
        expect(
          isBuilt(config, entry),
          `legalHref("${locale}", "${doc}") points at /${entry.replace(/\.html$/, "")}, ` +
            `but vite.config.ts has no "${entry}" build input`,
        ).toBe(true);
      }
    }
  });

  it("links every translated page that the build emits", () => {
    // The REVERSE direction, which the first case does not cover: a locale
    // whose pages were built but never allowlisted still resolves to the
    // English path, so the translation ships and nobody is ever sent to it.
    // Silent, and strictly worse than the 404 — a wrong-language contract
    // reads as correct.
    const config = viteConfig();
    for (const locale of UI_LOCALES) {
      for (const doc of ["terms", "privacy"] as const) {
        if (!isBuilt(config, `${locale}/${doc}.html`)) continue;
        expect(
          legalHref(locale, doc),
          `vite.config.ts builds "${locale}/${doc}.html", but legalHref("${locale}", ` +
            `"${doc}") still returns the English path — that page is unreachable`,
        ).toBe(`/${locale}/${doc}`);
      }
    }
  });
});
