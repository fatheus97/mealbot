import { describe, it, expect } from "vitest";
import {
  toISODate,
  todayISO,
  parseISODateLocal,
  dayDateLabel,
  formatISODate,
} from "./planDates";

describe("planDates", () => {
  describe("toISODate", () => {
    it("formats local components with zero-padding", () => {
      expect(toISODate(new Date(2026, 6, 21))).toBe("2026-07-21");
      expect(toISODate(new Date(2026, 0, 5))).toBe("2026-01-05");
      expect(toISODate(new Date(2026, 11, 31))).toBe("2026-12-31");
    });
  });

  describe("todayISO", () => {
    it("is a YYYY-MM-DD string matching today's local date", () => {
      expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(todayISO()).toBe(toISODate(new Date()));
    });
  });

  describe("parseISODateLocal", () => {
    it("parses to LOCAL midnight components (no UTC day-shift)", () => {
      const d = parseISODateLocal("2026-07-21");
      // The bug (new Date("2026-07-21")) parses as UTC midnight and reads back a
      // day early in negative-UTC zones. Asserting the local components proves we
      // build the date from y/m/d directly.
      expect(d.getFullYear()).toBe(2026);
      expect(d.getMonth()).toBe(6); // July (0-based)
      expect(d.getDate()).toBe(21);
    });

    it("round-trips with toISODate", () => {
      expect(toISODate(parseISODateLocal("2026-12-01"))).toBe("2026-12-01");
    });
  });

  describe("dayDateLabel", () => {
    it("returns null for an unscheduled plan", () => {
      expect(dayDateLabel(null, 0)).toBeNull();
      expect(dayDateLabel(undefined, 3)).toBeNull();
      expect(dayDateLabel("", 0)).toBeNull();
    });

    it("labels day N as start_date + (N-1)", () => {
      // 0-based dayIndex: day 0 = start date, day 1 = next day.
      expect(dayDateLabel("2026-07-21", 0)).toContain("21");
      expect(dayDateLabel("2026-07-21", 1)).toContain("22");
    });

    it("rolls over month boundaries", () => {
      // 2026-07-31 + 1 day = 2026-08-01.
      const label = dayDateLabel("2026-07-31", 1);
      expect(label).not.toBeNull();
      expect(label).toContain("1");
      // Distinct from the start day's label.
      expect(label).not.toBe(dayDateLabel("2026-07-31", 0));
    });
  });

  describe("formatISODate", () => {
    it("renders a human date containing the day and year", () => {
      const s = formatISODate("2026-07-21");
      expect(s).toContain("21");
      expect(s).toContain("2026");
    });
  });
});
