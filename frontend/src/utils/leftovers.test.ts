import { describe, it, expect } from "vitest";
import { leftoverSourceLabel, calendarLeftoverTitle } from "./leftovers";
import { formatISODate } from "./planDates";
import type { MealPlanResponse } from "../types";

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
    const label = leftoverSourceLabel(plan(), { day_index: 0, meal_index: 0 }, "2026-08-10");
    expect(label).toContain("Hot dinner");
    expect(label).toContain("Chicken Curry");
    expect(label).toContain("10"); // the source date
  });

  it("falls back to a positional day when the plan is unscheduled", () => {
    const label = leftoverSourceLabel(plan(), { day_index: 0, meal_index: 0 }, null);
    expect(label).toContain("Day 1");
    expect(label).toContain("Chicken Curry");
  });

  it("returns null for a null ref (an ordinary meal)", () => {
    expect(leftoverSourceLabel(plan(), null, "2026-08-10")).toBeNull();
    expect(leftoverSourceLabel(plan(), undefined, "2026-08-10")).toBeNull();
  });

  it("returns null for a null plan", () => {
    expect(leftoverSourceLabel(null, { day_index: 0, meal_index: 0 }, "2026-08-10")).toBeNull();
  });

  // THE reason every lookup is optional-chained: a stale link in a stored plan
  // would otherwise throw "Cannot read properties of undefined" mid-render and
  // unmount the whole planner. A missing subtitle is a far better outcome.
  it("returns null rather than throwing on an out-of-range day", () => {
    expect(() =>
      leftoverSourceLabel(plan(), { day_index: 9, meal_index: 0 }, "2026-08-10"),
    ).not.toThrow();
    expect(leftoverSourceLabel(plan(), { day_index: 9, meal_index: 0 }, "2026-08-10")).toBeNull();
  });

  it("returns null rather than throwing on an out-of-range meal", () => {
    expect(leftoverSourceLabel(plan(), { day_index: 0, meal_index: 9 }, "2026-08-10")).toBeNull();
  });

  it("survives a plan with no days array", () => {
    const broken = { plan_id: 1, start_date: null, shopping_list: [] } as unknown as MealPlanResponse;
    expect(leftoverSourceLabel(broken, { day_index: 0, meal_index: 0 }, null)).toBeNull();
  });
});

describe("calendarLeftoverTitle", () => {
  it("includes the source date and name when both are known", () => {
    const t = calendarLeftoverTitle("2026-08-10", "Chicken Curry", formatISODate);
    expect(t).toContain("Leftovers");
    expect(t).toContain("Chicken Curry");
    expect(t).toContain("10");
  });

  it("degrades to a bare marker when the server resolved neither", () => {
    expect(calendarLeftoverTitle(null, null, formatISODate)).toBe("Leftovers");
  });

  it("works with only a date", () => {
    const t = calendarLeftoverTitle("2026-08-10", null, formatISODate);
    expect(t).toContain("Leftovers");
    expect(t).not.toContain("—");
  });

  it("works with only a name", () => {
    const t = calendarLeftoverTitle(null, "Chicken Curry", formatISODate);
    expect(t).toContain("Chicken Curry");
  });
});
