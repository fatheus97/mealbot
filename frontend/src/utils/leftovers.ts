// Rendering helpers for leftover meals ("cook a bigger dinner, eat it as
// tomorrow's lunch"). A leftover carries a `leftover_of` pointer at an EARLIER
// meal in the same plan; the link is server-assigned and its indices are
// 0-based, addressing positions inside MealPlanResponse.days.

import { mealTypeLabel } from "../constants/mealTypes";
import type { LeftoverRef, MealPlanResponse } from "../types";
import { dayDateLabel } from "./planDates";
import type { TranslationKey } from "../i18n";
import type { Locale } from "../store/useLocaleStore";

/**
 * `t` from `useI18n`, narrowed to what these helpers need. Passed in rather
 * than imported so they stay pure and unit-testable — a hook cannot be called
 * outside a component anyway.
 */
type Translate = (
  key: TranslationKey,
  vars?: Record<string, string | number>,
) => string;

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
  locale: Locale,
  t: Translate,
): string | null {
  if (!plan || !ref) return null;
  const source = plan.days?.[ref.day_index]?.meals?.[ref.meal_index];
  if (!source) return null;

  // Falls back to the positional day number when the plan is unscheduled —
  // dayDateLabel returns null for a null/empty start date. That fallback was a
  // hardcoded `Day N`, so an unscheduled Czech plan read "Day 3" mid-sentence.
  const day =
    dayDateLabel(startISO, ref.day_index, locale) ??
    t("planner.day", { n: ref.day_index + 1 });
  const slot = mealTypeLabel(source.meal_type, source.meal_type_label);
  return `${day} · ${slot} — ${source.name}`;
}

// The compact narrow-screen label moved to the i18n dictionary
// (`meal.leftoversShort`) — an exported English constant could only ever be
// English, the same reason DIET_TYPE_LABELS was removed in #368.

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
  t: Translate,
): string {
  // One key per shape, not a stem plus appended fragments. Either half can be
  // unresolved independently, and Czech needs "z" + a genitive date and a colon
  // before the dish — neither survives being glued on after "Leftovers".
  if (sourceDate && sourceName) {
    return t("calendar.leftoverFromDateAndName", {
      date: formatDate(sourceDate),
      name: sourceName,
    });
  }
  if (sourceDate) return t("calendar.leftoverFromDate", { date: formatDate(sourceDate) });
  if (sourceName) return t("calendar.leftoverFromName", { name: sourceName });
  return t("meal.leftovers");
}
