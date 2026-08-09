import { describe, it, expect } from "vitest";
import { isExpired, STILL_FINE_EXTENSION_DAYS } from "./expiry";
import { todayISO, addDaysISO } from "./planDates";
import type { StockItem } from "../types";

function item(over: Partial<StockItem> = {}): StockItem {
  return {
    id: 1,
    name: "Yogurt",
    quantity_grams: 500,
    need_to_use: false,
    expiration_date: addDaysISO(todayISO(), -3),
    ...over,
  };
}

describe("isExpired", () => {
  it("is true only PAST the date, not on it", () => {
    // On the date itself the food is still within its own stated life, so
    // asking the user to judge it would be asking too early.
    expect(isExpired(item({ expiration_date: addDaysISO(todayISO(), -1) }))).toBe(true);
    expect(isExpired(item({ expiration_date: todayISO() }))).toBe(false);
    expect(isExpired(item({ expiration_date: addDaysISO(todayISO(), 1) }))).toBe(false);
  });

  it("is false for an item with no date at all", () => {
    expect(isExpired(item({ expiration_date: null }))).toBe(false);
  });

  it("is NARROWER than the fridge's need_to_use window", () => {
    // get_fridge_items auto-ticks need_to_use at today+2. "Use this up soon"
    // and "is this still edible?" are different questions, and prompting on
    // the former would train the user to click through the latter.
    const soon = item({ expiration_date: addDaysISO(todayISO(), 2), need_to_use: true });
    expect(isExpired(soon)).toBe(false);
  });

  it("compares far-apart years correctly as dates, not strings by length", () => {
    expect(isExpired(item({ expiration_date: "2019-12-31" }))).toBe(true);
    expect(isExpired(item({ expiration_date: "2099-01-01" }))).toBe(false);
  });
});

describe("STILL_FINE_EXTENSION_DAYS", () => {
  it("is a positive re-ask interval, so an answered item cannot stay expired", () => {
    // A zero or negative value would leave the item past its date, so the very
    // next finished plan would ask about it again — the loop this prevents.
    expect(STILL_FINE_EXTENSION_DAYS).toBeGreaterThan(0);
    const pushed = addDaysISO(todayISO(), STILL_FINE_EXTENSION_DAYS);
    expect(isExpired(item({ expiration_date: pushed }))).toBe(false);
  });
});
