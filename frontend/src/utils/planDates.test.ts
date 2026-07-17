import { describe, it, expect } from "vitest";
import {
  toISODate,
  todayISO,
  parseISODateLocal,
  dayDateLabel,
  formatISODate,
  startOfMonthISO,
  addMonthsISO,
  monthLabelOf,
  monthMatrix,
  isSameMonthISO,
  dayOfMonth,
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

  describe("month-grid helpers", () => {
    it("startOfMonthISO returns the 1st of the month", () => {
      expect(startOfMonthISO("2026-08-15")).toBe("2026-08-01");
      expect(startOfMonthISO("2026-02-28")).toBe("2026-02-01");
    });

    it("addMonthsISO moves whole months and rolls over the year", () => {
      expect(addMonthsISO("2026-08-01", 1)).toBe("2026-09-01");
      expect(addMonthsISO("2026-01-15", -1)).toBe("2025-12-01");
      expect(addMonthsISO("2026-12-10", 1)).toBe("2027-01-01");
    });

    it("monthMatrix is a 6×7 Sunday-start rectangle covering the month", () => {
      const weeks = monthMatrix("2026-08-01");
      expect(weeks).toHaveLength(6);
      weeks.forEach((w) => expect(w).toHaveLength(7));
      // First cell is a Sunday, on/before the 1st.
      expect(parseISODateLocal(weeks[0][0]).getDay()).toBe(0);
      const flat = weeks.flat();
      expect(flat).toContain("2026-08-01");
      expect(flat).toContain("2026-08-31");
      // Aug 1 2026 is a Saturday → the grid starts the prior Sunday (Jul 26).
      expect(weeks[0][0]).toBe("2026-07-26");
    });

    it("isSameMonthISO compares calendar month + year", () => {
      expect(isSameMonthISO("2026-08-31", "2026-08-01")).toBe(true);
      expect(isSameMonthISO("2026-09-01", "2026-08-01")).toBe(false);
      expect(isSameMonthISO("2025-08-15", "2026-08-01")).toBe(false);
    });

    it("dayOfMonth returns the day number", () => {
      expect(dayOfMonth("2026-08-05")).toBe(5);
      expect(dayOfMonth("2026-08-31")).toBe(31);
    });

    it("monthLabelOf includes the year", () => {
      expect(monthLabelOf("2026-08-10")).toContain("2026");
    });
  });
});
