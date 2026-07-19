// Rendering helpers for leftover meals ("cook a bigger dinner, eat it as
// tomorrow's lunch"). A leftover carries a `leftover_of` pointer at an EARLIER
// meal in the same plan; the link is server-assigned and its indices are
// 0-based, addressing positions inside MealPlanResponse.days.

import { mealTypeLabel } from "../constants/mealTypes";
import type { LeftoverRef, MealPlanResponse } from "../types";
import { dayDateLabel } from "./planDates";

/**
 * Human label for the meal a leftover came from, e.g.
 * "Sun Jul 19 · Hot dinner — Chicken curry".
 *
 * Returns null when the reference can't be resolved. Every lookup here is
 * OPTIONAL-CHAINED on purpose: a stale or out-of-range ref in a stored plan
 * would otherwise throw "Cannot read properties of undefined" during render,
 * which unmounts the entire planner — a far worse outcome than a missing
 * subtitle. The backend repairs bad links on write, but a plan fetched from
 * before that repair ran must still display.
 *
 * `startISO` should be the SAME expression the day headers use
 * (`isConfirmed ? currentPlan.start_date : startDate`), or the badge and the
 * header will disagree while the user is editing the date.
 */
export function leftoverSourceLabel(
  plan: MealPlanResponse | null | undefined,
  ref: LeftoverRef | null | undefined,
  startISO: string | null | undefined,
): string | null {
  if (!plan || !ref) return null;
  const source = plan.days?.[ref.day_index]?.meals?.[ref.meal_index];
  if (!source) return null;

  // Falls back to the positional day number when the plan is unscheduled —
  // dayDateLabel returns null for a null/empty start date.
  const day = dayDateLabel(startISO, ref.day_index) ?? `Day ${ref.day_index + 1}`;
  const slot = mealTypeLabel(source.meal_type, source.meal_type_label);
  return `${day} · ${slot} — ${source.name}`;
}

/** Compact form for narrow screens; the full label goes in `title`. */
export const LEFTOVER_SHORT_LABEL = "↻ Leftovers";

/**
 * Downcase only the FIRST character, so a sentence reads naturally when
 * embedded mid-phrase (e.g. inside parentheses).
 *
 * Lives here rather than in the component so it is importable — and therefore
 * testable — on its own. `.toLowerCase()` on the whole string was the original
 * bug: calendarLeftoverTitle returns "Leftovers from Aug 9, 2026 — Sunday
 * Roast", so flattening it mangled both the month abbreviation and the source
 * dish name, and the mobile agenda (which uses the helper untouched) then
 * disagreed with the grid about the same data.
 */
export function lowerFirst(s: string): string {
  return s.charAt(0).toLowerCase() + s.slice(1);
}

/**
 * Provenance line for a calendar chip, e.g. "Leftovers from Sun Aug 9 —
 * Sunday roast". Falls back gracefully when the server couldn't resolve the
 * source date or name.
 */
export function calendarLeftoverTitle(
  sourceDate: string | null,
  sourceName: string | null,
  formatDate: (iso: string) => string,
): string {
  const parts: string[] = [];
  if (sourceDate) parts.push(`from ${formatDate(sourceDate)}`);
  if (sourceName) parts.push(`— ${sourceName}`);
  return parts.length ? `Leftovers ${parts.join(" ")}` : "Leftovers";
}
