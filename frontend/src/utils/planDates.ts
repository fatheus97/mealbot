// Plan calendar dates. A plan carries an optional `start_date` (YYYY-MM-DD);
// day N (1-based) of the plan falls on start_date + (N - 1).
//
// Everything here is LOCAL-time. A bare `new Date("2026-07-21")` parses the
// string as UTC midnight, which renders as the *previous* day in any negative-
// UTC offset — the classic off-by-one date bug. So we build/read Date objects
// from explicit local components and never hand an ISO date string to the Date
// constructor.
//
// Every function that produces TEXT takes an explicit `locale`. They used to
// pass `undefined` to toLocaleDateString, which resolves to the BROWSER locale
// — so a Czech UI rendered "Mon Aug 10" wherever the browser was English. The
// app decides the language; `localeTags` lets the browser keep deciding the
// region.

import { localeTags } from "../i18n/localeFormat";
import type { Locale } from "../store/useLocaleStore";

/**
 * Index of the first day of the week, in `Date.getDay()` terms (0 = Sunday).
 *
 * A hardcoded table rather than `Intl.Locale.prototype.getWeekInfo()`: that API
 * only reached Chrome 130 / Safari 17 and is still absent from Firefox, so it
 * would silently disagree with itself across browsers — and a calendar grid
 * whose week starts on a different day than its own header row is a layout bug
 * you see instantly. Two locales, one line each, deterministic in tests.
 *
 * ponytail: swap for `getWeekInfo()` once it is baseline; the table is the only
 * thing that would need deleting.
 */
const FIRST_DAY_OF_WEEK: Record<Locale, number> = {
  en: 0, // Sunday — US convention, which the grid was hardcoded to
  cs: 1, // Monday — the ISO-8601 / Czech convention
};

export function firstDayOfWeek(locale: Locale): number {
  return FIRST_DAY_OF_WEEK[locale];
}

/**
 * The seven weekday headers, already rotated so index 0 is the locale's first
 * day. Generated from `Intl`, because the hardcoded `["Sun", "Mon", …]` this
 * replaces could only ever be English AND could only ever be Sunday-first.
 */
export function weekdayLabels(locale: Locale): string[] {
  const fmt = new Intl.DateTimeFormat(localeTags(locale), { weekday: "short" });
  // 2026-08-02 is a Sunday, so adding getDay()-style offsets to it names days
  // directly. Any Sunday works; a fixed one keeps this pure.
  const sunday = new Date(2026, 7, 2);
  const start = firstDayOfWeek(locale);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(sunday);
    d.setDate(sunday.getDate() + ((start + i) % 7));
    return fmt.format(d);
  });
}

/** A Date → "YYYY-MM-DD" using its LOCAL calendar components (not UTC). */
export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Today, in the browser's local timezone, as "YYYY-MM-DD". */
export function todayISO(): string {
  return toISODate(new Date());
}

/** Parse "YYYY-MM-DD" as a LOCAL-midnight Date (avoids the UTC-shift bug). */
export function parseISODateLocal(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/**
 * Human label for day `dayIndex0` (0-based) of a plan starting on `startISO`,
 * e.g. "Mon Jul 21". Returns null when the plan is unscheduled (`startISO`
 * null/empty) so callers fall back to the positional "Day N".
 */
export function dayDateLabel(
  startISO: string | null | undefined,
  dayIndex0: number,
  locale: Locale,
): string | null {
  if (!startISO) return null;
  const d = parseISODateLocal(startISO);
  d.setDate(d.getDate() + dayIndex0);
  return d.toLocaleDateString(localeTags(locale), {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** A single ISO date as a short human label, e.g. "Jul 21, 2026". */
export function formatISODate(iso: string, locale: Locale): string {
  return parseISODateLocal(iso).toLocaleDateString(localeTags(locale), {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// --- Month grid (calendar view) ---

/** First day of the month containing `iso`, as "YYYY-MM-DD". */
export function startOfMonthISO(iso: string): string {
  const d = parseISODateLocal(iso);
  return toISODate(new Date(d.getFullYear(), d.getMonth(), 1));
}

/**
 * `iso` shifted by `n` days (n may be negative), still "YYYY-MM-DD".
 *
 * Goes through a local-midnight Date so month/year rollover and DST are the
 * platform's problem, not ours — `new Date(y, m, d + n)` normalises overflow.
 */
export function addDaysISO(iso: string, n: number): string {
  const d = parseISODateLocal(iso);
  return toISODate(new Date(d.getFullYear(), d.getMonth(), d.getDate() + n));
}

/** First-of-month `n` months away from `iso` (n may be negative). */
export function addMonthsISO(iso: string, n: number): string {
  const d = parseISODateLocal(iso);
  return toISODate(new Date(d.getFullYear(), d.getMonth() + n, 1));
}

/**
 * e.g. "August 2026" — the month as a STANDALONE label (a heading, a caption).
 *
 * In Czech this is the nominative, "srpen 2026": correct on its own, wrong
 * inside a sentence. Use `monthLabelIn` there.
 */
export function monthLabelOf(iso: string, locale: Locale): string {
  return parseISODateLocal(iso).toLocaleDateString(localeTags(locale), {
    month: "long",
    year: "numeric",
  });
}

/**
 * Czech month names in the LOCATIVE case, indexed by `Date.getMonth()`.
 *
 * `Intl` has no notion of grammatical case — it returns one form per month — so
 * a language that inflects needs a table. Keyed on the month NUMBER rather than
 * derived from the nominative by a suffix rule: such a rule would have to be
 * re-verified against whatever spelling the current ICU ships, and "září" does
 * not inflect at all, so it would need a special case regardless.
 *
 * ponytail: a Czech-only table in a general util. It stays that way until a
 * second inflecting locale exists; the right shape then is a per-locale map,
 * not a rule engine.
 */
const CS_MONTHS_LOCATIVE = [
  "lednu",
  "únoru",
  "březnu",
  "dubnu",
  "květnu",
  "červnu",
  "červenci",
  "srpnu",
  "září", // indeclinable — "v září" is also the nominative
  "říjnu",
  "listopadu",
  "prosinci",
] as const;

/**
 * The month as it appears INSIDE a sentence, after "in" / "v" — e.g.
 * "No scheduled plans in {month}" / "V {month} nejsou…".
 *
 * English has no cases, so this is `monthLabelOf`. Czech takes the locative:
 * "v srpnu 2026", never "v srpen 2026". The calendar's empty state used the
 * standalone form and dodged the mismatch with "V měsíci {month}" — grammatical,
 * but it reads like a form letter.
 */
export function monthLabelIn(iso: string, locale: Locale): string {
  if (locale !== "cs") return monthLabelOf(iso, locale);
  const d = parseISODateLocal(iso);
  return `${CS_MONTHS_LOCATIVE[d.getMonth()]} ${d.getFullYear()}`;
}

/**
 * 6 weeks × 7 ISO dates covering the month of `monthCursorISO`, padded with the
 * trailing/leading days of the adjacent months so the grid is always a full
 * rectangle. weeks[0][0] is the first cell, weeks[5][6] the last — use those as
 * the API window bounds (≤ 42 days, well under the 92-day cap).
 *
 * `firstDay` is REQUIRED rather than defaulted to Sunday. The grid and its
 * header row have to agree, and a default is exactly how they would drift: the
 * header is derived from the locale, so a call site that forgot to pass this
 * would render Czech day names over US-ordered columns and look deliberate.
 * Pass `firstDayOfWeek(locale)`.
 */
export function monthMatrix(monthCursorISO: string, firstDay: number): string[][] {
  const first = parseISODateLocal(startOfMonthISO(monthCursorISO));
  const cursor = new Date(first);
  // Rewind to the most recent `firstDay`. The +7 keeps the modulo positive when
  // the month opens before it (a Sunday under a Monday-start locale rewinds 6
  // days, not -1).
  cursor.setDate(first.getDate() - ((first.getDay() - firstDay + 7) % 7));
  const weeks: string[][] = [];
  for (let w = 0; w < 6; w++) {
    const week: string[] = [];
    for (let d = 0; d < 7; d++) {
      week.push(toISODate(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  }
  return weeks;
}

/** True when `iso` is in the same calendar month as `monthCursorISO`. */
export function isSameMonthISO(iso: string, monthCursorISO: string): boolean {
  const a = parseISODateLocal(iso);
  const b = parseISODateLocal(monthCursorISO);
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth();
}

/** Day-of-month number, e.g. "2026-08-05" → 5. */
export function dayOfMonth(iso: string): number {
  return parseISODateLocal(iso).getDate();
}
