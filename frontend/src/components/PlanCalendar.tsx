import { useState } from "react";
import type { CSSProperties } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import { usePlanList, usePlanCalendar, useReschedulePlan } from "../hooks/useServerState";
import { fetchPlan } from "../api";
import { ModalShell } from "./ModalShell";
import {
  todayISO,
  startOfMonthISO,
  addMonthsISO,
  monthLabelOf,
  monthLabelIn,
  monthMatrix,
  isSameMonthISO,
  dayOfMonth,
  parseISODateLocal,
  formatISODate,
  firstDayOfWeek,
  weekdayLabels,
} from "../utils/planDates";
import { calendarLeftoverTitle, lowerFirst } from "../utils/leftovers";
import type { CalendarMeal, MealPlanResponse, MealPlanSummary, PlanStatus } from "../types";
import { useI18n } from "../i18n";
import { localeTags } from "../i18n/localeFormat";
import type { Locale } from "../store/useLocaleStore";

/** "Sat Aug 1" — a short weekday+date label for the agenda/list rows. */
function shortDayLabel(iso: string, locale: Locale): string {
  return parseISODateLocal(iso).toLocaleDateString(localeTags(locale), {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

// Status → chip colours (same palette as PlanCatalog). The whole calendar is an
// explicit light surface (#fff / dark text), so these fixed colours stay legible
// in both themes — the ModalShell backdrop handles the dark/light dimming.
// Not exported: the `findInlineColorPairs` source scan reads these pairs
// straight out of the file, so a re-export purely for the test would trip
// react-refresh/only-export-components for nothing.
const STATUS_COLORS: Record<PlanStatus, { bg: string; text: string }> = {
  planned: { bg: "#e2e8f0", text: "#475569" }, // 6.15:1
  active: { bg: "#dbeafe", text: "#1d4ed8" }, // 5.49:1
  // #16a34a was 3.00:1 here. The same colour was fixed twice already —
  // PantryStaples (3.29:1) and PlanCatalog — but this copy survived both
  // sweeps because the pair guard looks for `background`/`color` and this
  // record uses the `bg`/`text` shorthand. The guard now reads both.
  cooked: { bg: "#dcfce7", text: "#166534" }, // 6.49:1
  finished: { bg: "#f3e8ff", text: "#7c3aed" }, // 4.83:1
};

/**
 * The month grid is inside a modal that pins a light surface, so these are
 * fixed rather than theme-following. Ratios asserted in contrast.test.ts.
 */
export const OUT_OF_MONTH_SURFACE = "#f1f5f9";
export const OUT_OF_MONTH_DAY = "#475569"; // 6.92:1 on the tinted cell
export const IN_MONTH_DAY = "#374151"; // 10.31:1 on #fff
export const TODAY_COLOR = "#2563eb"; // 5.17:1 on #fff, 4.72:1 tinted

// Weekday headers are derived per-render from the locale (see weekdayLabels):
// the array that used to live here could only ever be English AND could only
// ever be Sunday-first, which is wrong for cs and for most of Europe.

const navBtn: CSSProperties = {
  minWidth: 32,
  height: 32,
  borderRadius: 6,
  border: "1px solid #d1d5db",
  background: "#fff",
  color: "#111827",
  cursor: "pointer",
  fontSize: "1rem",
  lineHeight: 1,
};

function chipStyle(status: PlanStatus): CSSProperties {
  const c = STATUS_COLORS[status];
  return {
    backgroundColor: c.bg,
    color: c.text,
    border: "none",
    borderRadius: 4,
    padding: "1px 5px",
    fontSize: "0.7rem",
    fontWeight: 600,
    cursor: "pointer",
    textAlign: "left",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    maxWidth: "100%",
  };
}

interface PlanCalendarProps {
  onClose: () => void;
  onOpenPlan: (plan: MealPlanResponse, summary: MealPlanSummary) => void;
}

interface DayChip {
  plan_id: number;
  status: PlanStatus;
  // Objects, not names: a leftover needs a marker and its provenance. Kept in
  // lockstep with CalendarDay.meals — widening one without the other renders
  // "[object Object]" with no type error at the join site.
  meals: CalendarMeal[];
}

export function PlanCalendar({ onClose, onOpenPlan }: PlanCalendarProps) {
  const { t, locale } = useI18n();
  const weekdays = weekdayLabels(locale);
  const { userId } = useAuth();
  const isMobile = useIsMobile();
  const [monthCursor, setMonthCursor] = useState<string>(() => startOfMonthISO(todayISO()));
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [rescheduleError, setRescheduleError] = useState<string | null>(null);
  // Bumped on a failed reschedule so the (uncontrolled) date inputs remount on
  // the server value — otherwise a failed input keeps showing the unsaved date.
  const [inputNonce, setInputNonce] = useState(0);

  const weeks = monthMatrix(monthCursor, firstDayOfWeek(locale));
  const from = weeks[0][0];
  const to = weeks[5][6];

  const { data: calendar, isLoading } = usePlanCalendar(userId, from, to);
  // Shares the ['planList'] cache with PlanCatalog — the summary a click needs to
  // open a plan comes from here (calendar plans are always confirmed → listed).
  const { data: planList } = usePlanList(userId);
  const rescheduleMutation = useReschedulePlan();

  const plans = calendar?.plans ?? [];

  // date → chips, built from every plan's per-day cells.
  const byDate = new Map<string, DayChip[]>();
  for (const p of plans) {
    for (const day of p.days) {
      const arr = byDate.get(day.date) ?? [];
      arr.push({ plan_id: p.plan_id, status: p.status, meals: day.meals });
      byDate.set(day.date, arr);
    }
  }

  const handleOpen = async (planId: number) => {
    const summary = planList?.find((s) => s.id === planId);
    if (!summary) {
      setOpenError(t("plans.openFailed"));
      return;
    }
    setOpeningId(planId);
    setOpenError(null);
    try {
      const plan = await fetchPlan(planId);
      onOpenPlan(plan, summary);
      onClose();
    } catch {
      setOpenError(t("plans.openFailed"));
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <ModalShell onClose={onClose} ariaLabel={t("calendar.title")}>
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: "#fff",
          color: "#1f2937",
          width: isMobile ? "100%" : "min(96vw, 860px)",
          height: isMobile ? "100%" : "min(90vh, 720px)",
          borderRadius: isMobile ? 0 : "10px",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          fontFamily: "sans-serif",
          boxShadow: "0 12px 40px rgba(0,0,0,0.4)",
        }}
      >
        {/* Header: month nav + close */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0.85rem 1rem",
            borderBottom: "1px solid #e5e7eb",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <button aria-label={t("calendar.previousMonth")} onClick={() => setMonthCursor(addMonthsISO(monthCursor, -1))} style={navBtn}>‹</button>
            <strong style={{ minWidth: isMobile ? 116 : 150, textAlign: "center" }}>
              {monthLabelOf(monthCursor, locale)}
            </strong>
            <button aria-label={t("calendar.nextMonth")} onClick={() => setMonthCursor(addMonthsISO(monthCursor, 1))} style={navBtn}>›</button>
            <button
              onClick={() => setMonthCursor(startOfMonthISO(todayISO()))}
              style={{ ...navBtn, minWidth: "auto", padding: "0 0.6rem", fontSize: "0.78rem" }}
            >
              {t("calendar.today")}
            </button>
          </div>
          <button aria-label={t("calendar.close")} onClick={onClose} style={{ ...navBtn, fontSize: "1.15rem" }}>✕</button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "0.75rem 1rem 1.25rem" }}>
          {isLoading && <p style={{ color: "#6b7280" }}>{t("calendar.loading")}</p>}

          {/* Desktop: month grid (chips click-to-open). Mobile falls back to the
              agenda list below — a 7-col grid is unusable at 375px. */}
          {!isMobile && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: "2px", marginBottom: "1rem" }}>
              {weekdays.map((w) => (
                <div key={w} style={{ textAlign: "center", fontSize: "0.72rem", fontWeight: 600, color: "#6b7280", padding: "0.2rem 0" }}>
                  {w}
                </div>
              ))}
              {weeks.flat().map((date) => {
                const inMonth = isSameMonthISO(date, monthCursor);
                const chips = byDate.get(date) ?? [];
                const isToday = date === todayISO();
                return (
                  <div
                    key={date}
                    style={{
                      minHeight: 82,
                      border: "1px solid #eef2f7",
                      borderRadius: 6,
                      padding: 3,
                      // Adjacent-month cells are de-emphasised by SURFACE, not
                      // by dimming. `opacity: 0.5` on the cell multiplies every
                      // descendant: the day number measured 2.58:1, and it also
                      // dragged the status chips — which are enabled BUTTONS
                      // with their own AA-checked colour pair — down to 2.33:1.
                      // An ancestor's opacity is invisible to findInlineColorPairs,
                      // so the guard kept reporting the chips' undimmed ratios.
                      // No opacity value works either: at 0.85 the chips still
                      // fail, and `today` (which lands in an adjacent-month cell
                      // whenever you page forward a month) never clears 4.5.
                      backgroundColor: inMonth ? "#fff" : OUT_OF_MONTH_SURFACE,
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                      overflow: "hidden",
                    }}
                  >
                    <span
                      style={{
                        fontSize: "0.72rem",
                        fontWeight: isToday ? 700 : 500,
                        // The remaining half of the de-emphasis: a muted (but
                        // still AA) number rather than a dimmed one.
                        color: isToday ? TODAY_COLOR : inMonth ? IN_MONTH_DAY : OUT_OF_MONTH_DAY,
                        alignSelf: "flex-end",
                      }}
                    >
                      {dayOfMonth(date)}
                    </span>
                    {chips.map((c, i) => (
                      // All of that day's meals, stacked in day-layout order
                      // (breakfast → … → dinner). One button per plan-day → open.
                      <button
                        key={`${c.plan_id}-${i}`}
                        onClick={() => handleOpen(c.plan_id)}
                        disabled={openingId === c.plan_id}
                        title={
                          c.meals
                            .map((m) =>
                              m.is_leftover
                                ? `${m.name} (${lowerFirst(
                                    calendarLeftoverTitle(
                                      m.source_date, m.source_name,
                                      (iso) => formatISODate(iso, locale), t,
                                    ),
                                  )})`
                                : m.name,
                            )
                            .join(", ") || t("calendar.planNumbered", { id: c.plan_id })
                        }
                        style={{
                          backgroundColor: STATUS_COLORS[c.status].bg,
                          color: STATUS_COLORS[c.status].text,
                          border: "none",
                          borderRadius: 4,
                          padding: "2px 4px",
                          fontSize: "0.68rem",
                          fontWeight: 600,
                          cursor: "pointer",
                          textAlign: "left",
                          width: "100%",
                          display: "flex",
                          flexDirection: "column",
                          gap: 1,
                        }}
                      >
                        {c.meals.length > 0 ? (
                          // A leftover gets a glyph + italic ONLY. Deliberately
                          // no background colour: the chip background already
                          // encodes plan status (STATUS_COLORS), and a second
                          // colour axis on the same element collides. And no
                          // extra sub-line — the cell is minHeight 82 with
                          // overflow hidden and no scroll, so anything taller
                          // silently clips the later meals of that day.
                          c.meals.map((m, j) => (
                            <span
                              key={j}
                              style={{
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                maxWidth: "100%",
                                fontStyle: m.is_leftover ? "italic" : "normal",
                                fontWeight: m.is_leftover ? 400 : 600,
                              }}
                            >
                              {m.is_leftover ? `↻ ${m.name}` : m.name}
                            </span>
                          ))
                        ) : (
                          <span>{t("calendar.plan")}</span>
                        )}
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          )}

          {openError && (
            <p role="alert" style={{ color: "#b91c1c", fontSize: "0.85rem", marginTop: 0 }}>
              {openError}
            </p>
          )}
          {rescheduleError && (
            <p role="alert" style={{ color: "#b91c1c", fontSize: "0.85rem", marginTop: 0 }}>
              {rescheduleError}
            </p>
          )}

          {/* Actionable list: open a plan, or reschedule / unschedule its date.
              On mobile this is the whole calendar (agenda); on desktop it sits
              under the grid so the reschedule controls aren't crammed into cells. */}
          <div>
            {!isMobile && (
              <h4 style={{ margin: "0 0 0.5rem", fontSize: "0.88rem", color: "#374151" }}>
                {t("calendar.scheduled")}
              </h4>
            )}
            {!isLoading && plans.length === 0 && (
              <p style={{ color: "#6b7280", fontSize: "0.9rem", margin: 0 }}>
                {/* monthLabelIN, not monthLabelOf: this one sits inside a sentence, and
                    Czech needs the locative there ("V srpnu 2026", not "V srpen
                    2026"). The heading above keeps the standalone form. */}
                {t("calendar.emptyMonth", { month: monthLabelIn(monthCursor, locale) })}
              </p>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
              {plans.map((p) => (
                <div
                  key={p.plan_id}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.35rem",
                    padding: "0.55rem 0.65rem",
                    border: "1px solid #e5e7eb",
                    borderRadius: 6,
                    backgroundColor: "#f9fafb",
                  }}
                >
                  {/* Header row: status · reschedule · open */}
                  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem" }}>
                    <span style={{ ...chipStyle(p.status), cursor: "default" }}>
                      {t(`planStatus.${p.status}` as const)}
                    </span>
                    <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.8rem", color: "#374151" }}>
                      <span aria-hidden>📅</span>
                      {/* Uncontrolled + keyed on the server value: picking a new
                          date fires reschedule; when the refetch lands, the key
                          flips and the input remounts on the new date — no
                          snap-back flicker. */}
                      <input
                        key={`${p.start_date}-${inputNonce}`}
                        type="date"
                        aria-label={`Reschedule plan ${p.plan_id}`}
                        defaultValue={p.start_date}
                        onChange={(e) =>
                          rescheduleMutation.mutate(
                            { planId: p.plan_id, startDate: e.target.value || null },
                            {
                              onSuccess: () => setRescheduleError(null),
                              onError: () => {
                                setRescheduleError(
                                  t("calendar.rescheduleFailed"),
                                );
                                // Remount the inputs so the failed one snaps back
                                // to the server date instead of an unsaved value.
                                setInputNonce((n) => n + 1);
                              },
                            },
                          )
                        }
                        style={{ padding: "0.2rem 0.3rem", fontSize: "0.8rem" }}
                      />
                    </label>
                    <span style={{ flex: 1 }} />
                    <button
                      onClick={() => handleOpen(p.plan_id)}
                      disabled={openingId === p.plan_id}
                      style={{ background: "none", border: "none", color: "#1d4ed8", cursor: "pointer", fontWeight: 600, padding: 0, fontSize: "0.85rem" }}
                    >
                      {openingId === p.plan_id ? t("calendar.openingPlan") : t("calendar.openPlan")}
                    </button>
                  </div>
                  {/* Every day's meals, in day-layout order (breakfast → dinner). */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    {p.days.map((d) => (
                      <div key={d.day_index} style={{ fontSize: "0.8rem", color: "#374151", lineHeight: 1.3 }}>
                        <strong style={{ color: "#6b7280", fontWeight: 600, marginRight: "0.4rem" }}>
                          {shortDayLabel(d.date, locale)}
                        </strong>
                        {/* A JSX map, not .join(" · ") — the meals are objects
                            now, and joining them would silently render
                            "[object Object]" with no type error. This list IS
                            the entire mobile calendar (there is no grid below
                            768px), so it carries the leftover marker too. */}
                        {d.meals.length
                          ? d.meals.map((m, j) => (
                              <span key={j}>
                                {j > 0 && " · "}
                                <span
                                  title={
                                    m.is_leftover
                                      ? calendarLeftoverTitle(
                                          m.source_date, m.source_name,
                                          (iso) => formatISODate(iso, locale), t,
                                        )
                                      : undefined
                                  }
                                  style={{
                                    fontStyle: m.is_leftover ? "italic" : "normal",
                                  }}
                                >
                                  {m.is_leftover ? `↻ ${m.name}` : m.name}
                                </span>
                              </span>
                            ))
                          : "—"}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </ModalShell>
  );
}
