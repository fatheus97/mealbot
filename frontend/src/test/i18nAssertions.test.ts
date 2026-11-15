import { describe, it, expect } from "vitest";
import { untranslatedEnglishIn } from "./i18nAssertions";

function node(text: string): HTMLElement {
  const div = document.createElement("div");
  div.textContent = text;
  return div;
}

describe("untranslatedEnglishIn", () => {
  it("lets a proper name through, and still catches the English word inside it", () => {
    // Czech copy names the database in English; its "Open" is not a missed key.
    expect(untranslatedEnglishIn(node("Obsahuje informace z databáze Open Food Facts."))).toEqual([]);
    // The control: the same word as a label of its own is a missed translation.
    expect(untranslatedEnglishIn(node("Open"))).toContain("plans.open: Open");
    expect(untranslatedEnglishIn(node("Open Food Facts · Open"))).toContain("plans.open: Open");
  });
});
