import { describe, it, expect } from "vitest";
import {
  toISODate,
  todayISO,
  parseISODateLocal,
  dayDateLabel,
  formatISODate,
  startOfMonthISO,
  addDaysISO,
  addMonthsISO,
  monthLabelOf,
  monthLabelIn,
  monthMatrix,
  isSameMonthISO,
  dayOfMonth,
  firstDayOfWeek,
  weekdayLabels,
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
      expect(dayDateLabel(null, 0, "en")).toBeNull();
      expect(dayDateLabel(undefined, 3, "en")).toBeNull();
      expect(dayDateLabel("", 0, "en")).toBeNull();
    });

    it("labels day N as start_date + (N-1)", () => {
      // 0-based dayIndex: day 0 = start date, day 1 = next day.
      expect(dayDateLabel("2026-07-21", 0, "en")).toContain("21");
      expect(dayDateLabel("2026-07-21", 1, "en")).toContain("22");
    });

    it("rolls over month boundaries", () => {
      // 2026-07-31 + 1 day = 2026-08-01.
      const label = dayDateLabel("2026-07-31", 1, "en");
      expect(label).not.toBeNull();
      expect(label).toContain("1");
      // Distinct from the start day's label.
      expect(label).not.toBe(dayDateLabel("2026-07-31", 0, "en"));
    });
  });

  describe("formatISODate", () => {
    it("renders a human date containing the day and year", () => {
      const s = formatISODate("2026-07-21", "en");
      expect(s).toContain("21");
      expect(s).toContain("2026");
    });
  });

  describe("month-grid helpers", () => {
    it("startOfMonthISO returns the 1st of the month", () => {
      expect(startOfMonthISO("2026-08-15")).toBe("2026-08-01");
      expect(startOfMonthISO("2026-02-28")).toBe("2026-02-01");
    });

    it("addDaysISO shifts days and normalises month/year rollover", () => {
      expect(addDaysISO("2026-08-09", 7)).toBe("2026-08-16");
      // Month rollover, and a month shorter than 31 days.
      expect(addDaysISO("2026-08-28", 7)).toBe("2026-09-04");
      // Year rollover, both directions.
      expect(addDaysISO("2026-12-28", 7)).toBe("2027-01-04");
      expect(addDaysISO("2026-01-03", -7)).toBe("2025-12-27");
      // Leap day is the platform's job, not ours.
      expect(addDaysISO("2028-02-28", 1)).toBe("2028-02-29");
      expect(addDaysISO("2026-02-28", 1)).toBe("2026-03-01");
    });

    it("addMonthsISO moves whole months and rolls over the year", () => {
      expect(addMonthsISO("2026-08-01", 1)).toBe("2026-09-01");
      expect(addMonthsISO("2026-01-15", -1)).toBe("2025-12-01");
      expect(addMonthsISO("2026-12-10", 1)).toBe("2027-01-01");
    });

    it("monthMatrix is a 6×7 rectangle starting on the locale's first day", () => {
      const weeks = monthMatrix("2026-08-01", 0);
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
      expect(monthLabelOf("2026-08-10", "en")).toContain("2026");
    });
  });

  describe("locale", () => {
    // All three used to pass `undefined` to toLocaleDateString, i.e. the
    // BROWSER locale. jsdom reports en-US, so a Czech UI rendered English month
    // and weekday names — invisible to every test that only ran in English.
    it("names months and weekdays in the app locale, not the browser's", () => {
      expect(monthLabelOf("2026-08-10", "en")).toMatch(/August/);
      expect(monthLabelOf("2026-08-10", "cs")).not.toMatch(/August/);

      expect(dayDateLabel("2026-08-10", 0, "en")).toMatch(/Aug/);
      expect(dayDateLabel("2026-08-10", 0, "cs")).not.toMatch(/Aug/);

      expect(formatISODate("2026-08-10", "en")).toMatch(/Aug/);
      expect(formatISODate("2026-08-10", "cs")).not.toMatch(/Aug/);
    });

    it("starts the week on Sunday for en and Monday for cs", () => {
      // Not cosmetic: the grid and its header row are generated from this same
      // number, so getting it wrong files every date under the wrong column.
      expect(firstDayOfWeek("en")).toBe(0);
      expect(firstDayOfWeek("cs")).toBe(1);
    });

    it("rotates the weekday headers to match, in the right language", () => {
      const en = weekdayLabels("en");
      const cs = weekdayLabels("cs");
      expect(en).toHaveLength(7);
      expect(cs).toHaveLength(7);
      expect(en[0]).toMatch(/^Sun/);
      expect(cs[0]).not.toMatch(/^Sun/);
      expect(cs[0]).not.toBe(en[0]);
      // All seven distinct — a rotation bug that repeated a day shows up here.
      expect(new Set(cs).size).toBe(7);
    });

    it("aligns the grid's first cell with the locale's first day", () => {
      // Aug 1 2026 is a Saturday. Sunday-start rewinds to Jul 26, Monday-start
      // to Jul 27 — exactly the off-by-one a hardcoded Sunday grid produced
      // under a Czech header row.
      const sun = monthMatrix("2026-08-01", 0);
      const mon = monthMatrix("2026-08-01", 1);
      expect(sun[0][0]).toBe("2026-07-26");
      expect(mon[0][0]).toBe("2026-07-27");
      expect(parseISODateLocal(sun[0][0]).getDay()).toBe(0);
      expect(parseISODateLocal(mon[0][0]).getDay()).toBe(1);
      for (const weeks of [sun, mon]) {
        const flat = weeks.flat();
        expect(flat).toContain("2026-08-01");
        expect(flat).toContain("2026-08-31");
      }
    });

    it("rewinds a full week when the month opens on the locale's first day", () => {
      // Feb 2026 opens on a Sunday. Under a Monday-start locale that must
      // rewind 6 days, which is what the `+ 7` in the modulo buys: a bare
      // (getDay() - firstDay) would be -1 and push the grid FORWARD, dropping
      // Feb 1 out of it entirely.
      expect(parseISODateLocal("2026-02-01").getDay()).toBe(0);
      const mon = monthMatrix("2026-02-01", 1);
      expect(mon[0][0]).toBe("2026-01-26");
      expect(mon.flat()).toContain("2026-02-01");
    });
  });

  describe("monthLabelIn (the locative)", () => {
    // Every month spelled out. A hand-written table's failure mode is ONE wrong
    // entry, which a spot-check of August would sail past — and nothing else in
    // the app would catch it, because Intl never produces this form.
    it.each([
      ["2026-01-05", "lednu"],
      ["2026-02-05", "únoru"],
      ["2026-03-05", "březnu"],
      ["2026-04-05", "dubnu"],
      ["2026-05-05", "květnu"],
      ["2026-06-05", "červnu"],
      ["2026-07-05", "červenci"],
      ["2026-08-05", "srpnu"],
      ["2026-09-05", "září"],
      ["2026-10-05", "říjnu"],
      ["2026-11-05", "listopadu"],
      ["2026-12-05", "prosinci"],
    ])("renders %s as '%s 2026' in Czech", (iso, expected) => {
      expect(monthLabelIn(iso, "cs")).toBe(`${expected} 2026`);
    });

    it("differs from the standalone form for every month except září", () => {
      // září is indeclinable, so nominative and locative coincide — and that is
      // the one month where "they must differ" would be a WRONG assertion.
      for (let m = 0; m < 12; m++) {
        const iso = `2026-${String(m + 1).padStart(2, "0")}-05`;
        const standalone = monthLabelOf(iso, "cs");
        const inSentence = monthLabelIn(iso, "cs");
        if (m === 8) expect(inSentence).toBe(standalone);
        else expect(inSentence).not.toBe(standalone);
      }
    });

    it("leaves English alone — it has no cases to get wrong", () => {
      expect(monthLabelIn("2026-08-05", "en")).toBe(monthLabelOf("2026-08-05", "en"));
      expect(monthLabelIn("2026-08-05", "en")).toMatch(/August 2026/);
    });

    it("keeps the year, and the right one across a year boundary", () => {
      expect(monthLabelIn("2025-12-31", "cs")).toBe("prosinci 2025");
      expect(monthLabelIn("2026-01-01", "cs")).toBe("lednu 2026");
    });
  });
});
