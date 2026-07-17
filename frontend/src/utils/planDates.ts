// Plan calendar dates. A plan carries an optional `start_date` (YYYY-MM-DD);
// day N (1-based) of the plan falls on start_date + (N - 1).
//
// Everything here is LOCAL-time. A bare `new Date("2026-07-21")` parses the
// string as UTC midnight, which renders as the *previous* day in any negative-
// UTC offset — the classic off-by-one date bug. So we build/read Date objects
// from explicit local components and never hand an ISO date string to the Date
// constructor.

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
): string | null {
  if (!startISO) return null;
  const d = parseISODateLocal(startISO);
  d.setDate(d.getDate() + dayIndex0);
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** A single ISO date as a short human label, e.g. "Jul 21, 2026". */
export function formatISODate(iso: string): string {
  return parseISODateLocal(iso).toLocaleDateString(undefined, {
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

/** First-of-month `n` months away from `iso` (n may be negative). */
export function addMonthsISO(iso: string, n: number): string {
  const d = parseISODateLocal(iso);
  return toISODate(new Date(d.getFullYear(), d.getMonth() + n, 1));
}

/** e.g. "August 2026" for any date in that month. */
export function monthLabelOf(iso: string): string {
  return parseISODateLocal(iso).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

/**
 * 6 weeks × 7 ISO dates (Sunday-start) covering the month of `monthCursorISO`,
 * padded with the trailing/leading days of the adjacent months so the grid is
 * always a full rectangle. weeks[0][0] is the first cell, weeks[5][6] the last —
 * use those as the API window bounds (≤ 42 days, well under the 92-day cap).
 */
export function monthMatrix(monthCursorISO: string): string[][] {
  const first = parseISODateLocal(startOfMonthISO(monthCursorISO));
  const cursor = new Date(first);
  cursor.setDate(first.getDate() - first.getDay()); // rewind to the week's Sunday
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
