import { describe, it, expect } from "vitest";
import { leftoverSourceLabel, calendarLeftoverTitle, lowerFirst } from "./leftovers";
import { formatISODate } from "./planDates";
import type { MealPlanResponse } from "../types";

import { makeI18n } from "../i18n";

// The app's REAL t, not a reimplementation. An earlier revision hand-rolled the
// interpolation here, which review rightly flagged: a test helper that
// duplicates the logic under test can agree with itself while both are wrong.
const tr = makeI18n("en").t;

const fmtEn = (iso: string) => formatISODate(iso, "en");

function plan(): MealPlanResponse {
  return {
    plan_id: 1,
    start_date: "2026-08-10",
    days: [
      {
        meals: [
          {
            name: "Chicken Curry",
            meal_type: "hot_dinner",
            meal_type_label: "Hot dinner",
            ingredients: [],
            steps: [],
          },
        ],
      },
      {
        meals: [
          {
            name: "Leftovers: Chicken Curry",
            meal_type: "light_lunch",
            meal_type_label: "Light lunch",
            ingredients: [],
            steps: [],
            leftover_of: { day_index: 0, meal_index: 0 },
          },
        ],
      },
    ],
    shopping_list: [],
  };
}

describe("leftoverSourceLabel", () => {
  it("resolves the source day, slot and dish", () => {
    const label = leftoverSourceLabel(plan(), { day_index: 0, meal_index: 0 }, "2026-08-10", "en", tr);
    expect(label).toContain("Hot dinner");
    expect(label).toContain("Chicken Curry");
    expect(label).toContain("10"); // the source date
  });

  it("falls back to a positional day when the plan is unscheduled", () => {
    const label = leftoverSourceLabel(plan(), { day_index: 0, meal_index: 0 }, null, "en", tr);
    expect(label).toContain("Day 1");
    expect(label).toContain("Chicken Curry");
  });

  it("returns null for a null ref (an ordinary meal)", () => {
    expect(leftoverSourceLabel(plan(), null, "2026-08-10", "en", tr)).toBeNull();
    expect(leftoverSourceLabel(plan(), undefined, "2026-08-10", "en", tr)).toBeNull();
  });

  it("returns null for a null plan", () => {
    expect(leftoverSourceLabel(null, { day_index: 0, meal_index: 0 }, "2026-08-10", "en", tr)).toBeNull();
  });

  // THE reason every lookup is optional-chained: a stale link in a stored plan
  // would otherwise throw "Cannot read properties of undefined" mid-render and
  // unmount the whole planner. A missing subtitle is a far better outcome.
  it("returns null rather than throwing on an out-of-range day", () => {
    expect(() =>
      leftoverSourceLabel(plan(), { day_index: 9, meal_index: 0 }, "2026-08-10", "en", tr),
    ).not.toThrow();
    expect(
      leftoverSourceLabel(plan(), { day_index: 9, meal_index: 0 }, "2026-08-10", "en", tr),
    ).toBeNull();
  });

  it("returns null rather than throwing on an out-of-range meal", () => {
    expect(
      leftoverSourceLabel(plan(), { day_index: 0, meal_index: 9 }, "2026-08-10", "en", tr),
    ).toBeNull();
  });

  it("survives a plan with no days array", () => {
    const broken = { plan_id: 1, start_date: null, shopping_list: [] } as unknown as MealPlanResponse;
    expect(leftoverSourceLabel(broken, { day_index: 0, meal_index: 0 }, null, "en", tr)).toBeNull();
  });
});

describe("calendarLeftoverTitle", () => {
  it("includes the source date and name when both are known", () => {
    const t = calendarLeftoverTitle("2026-08-10", "Chicken Curry", fmtEn, tr);
    expect(t).toContain("Leftovers");
    expect(t).toContain("Chicken Curry");
    expect(t).toContain("10");
  });

  it("degrades to a bare marker when the server resolved neither", () => {
    expect(calendarLeftoverTitle(null, null, fmtEn, tr)).toBe("Leftovers");
  });

  it("works with only a date", () => {
    const t = calendarLeftoverTitle("2026-08-10", null, fmtEn, tr);
    expect(t).toContain("Leftovers");
    expect(t).not.toContain("—");
  });

  it("works with only a name", () => {
    const t = calendarLeftoverTitle(null, "Chicken Curry", fmtEn, tr);
    expect(t).toContain("Chicken Curry");
  });

  describe("in Czech", () => {
    const trCs = makeI18n("cs").t;
    const fmtCs = (iso: string) => formatISODate(iso, "cs");

    it("translates the unscheduled-plan day fallback", () => {
      // Was a hardcoded `Day ${n + 1}`, so an unscheduled Czech plan read
      // "Day 1 · Hot dinner — Chicken Curry" with one English word wedged in.
      const label = leftoverSourceLabel(
        plan(),
        { day_index: 0, meal_index: 0 },
        null,
        "cs",
        trCs,
      );
      expect(label).not.toBeNull();
      expect(label).not.toContain("Day ");
      expect(label).toContain("Chicken Curry"); // the dish is the model's, untouched
    });

    it("translates the calendar provenance line and its date", () => {
      const title = calendarLeftoverTitle("2026-08-10", "Chicken Curry", fmtCs, trCs);
      expect(title).not.toContain("Leftovers");
      expect(title).not.toMatch(/Aug/);
      expect(title).toContain("Chicken Curry");
    });

    it("keeps every shape a whole sentence, not a glued stem", () => {
      // The English version appended " from …" and " — …" to a shared
      // "Leftovers" stem. Czech needs "z" + a genitive date and a colon before
      // the dish, so each shape is its own key — and none may be left holding a
      // dangling separator when the server resolved only half.
      for (const title of [
        calendarLeftoverTitle("2026-08-10", null, fmtCs, trCs),
        calendarLeftoverTitle(null, "Chicken Curry", fmtCs, trCs),
        calendarLeftoverTitle(null, null, fmtCs, trCs),
      ]) {
        expect(title.trim()).toBe(title);
        expect(title).not.toMatch(/[:—]\s*$/);
        expect(title).not.toMatch(/\s{2,}/);
      }
    });
  });
});

describe("calendar tooltip casing", () => {
  // The grid chip embeds this sentence in parentheses and needs a lowercase
  // lead-in. Downcasing the WHOLE string flattened the month abbreviation and
  // the source dish name — and the mobile agenda, which uses the helper
  // untouched, then disagreed with the grid about the same data.
  it("preserves the source name and month when lead-in is downcased", () => {
    const full = calendarLeftoverTitle("2026-08-09", "Sunday Roast", fmtEn, tr);
    const embedded = lowerFirst(full);
    expect(embedded).toContain("Sunday Roast");
    expect(embedded).toMatch(/Aug/);
    expect(embedded.startsWith("leftovers")).toBe(true);
    expect(embedded).not.toContain("sunday roast");
    expect(embedded).not.toContain("aug");
  });
});
