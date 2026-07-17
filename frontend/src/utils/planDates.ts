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
