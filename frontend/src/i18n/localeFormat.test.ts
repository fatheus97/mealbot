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

  it("only points at pages the build actually emits", () => {
    // The guard the allowlist's docstring promises. A locale added to
    // UI_LOCALES without its legal pages being added to the Vite build (or
    // vice versa) is a link to a 404 on the page where money changes hands,
    // and nothing else in the suite would notice: the SPA never navigates
    // there, so no render test can follow the href.
    const viteConfig = readFileSync(
      resolve(import.meta.dirname, "../../vite.config.ts"),
      "utf-8",
    );
    for (const locale of UI_LOCALES) {
      for (const doc of ["terms", "privacy"] as const) {
        const entry = `${legalHref(locale, doc).replace(/^\//, "")}.html`;
        expect(
          viteConfig.includes(`'${entry}'`) || viteConfig.includes(`"${entry}"`),
          `legalHref("${locale}", "${doc}") points at /${entry.replace(/\.html$/, "")}, ` +
            `but vite.config.ts has no "${entry}" build input`,
        ).toBe(true);
      }
    }
  });
});
