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
  monthMatrix,
  isSameMonthISO,
  dayOfMonth,
} from "../utils/planDates";
import type { MealPlanResponse, MealPlanSummary, PlanStatus } from "../types";

// Status → chip colours (same palette as PlanCatalog). The whole calendar is an
// explicit light surface (#fff / dark text), so these fixed colours stay legible
// in both themes — the ModalShell backdrop handles the dark/light dimming.
const STATUS_COLORS: Record<PlanStatus, { bg: string; text: string }> = {
  planned: { bg: "#e2e8f0", text: "#475569" },
  active: { bg: "#dbeafe", text: "#1d4ed8" },
  cooked: { bg: "#dcfce7", text: "#16a34a" },
  finished: { bg: "#f3e8ff", text: "#7c3aed" },
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

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
  meals: string[];
}

export function PlanCalendar({ onClose, onOpenPlan }: PlanCalendarProps) {
  const { userId } = useAuth();
  const isMobile = useIsMobile();
  const [monthCursor, setMonthCursor] = useState<string>(() => startOfMonthISO(todayISO()));
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const weeks = monthMatrix(monthCursor);
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
      setOpenError("Couldn't open that plan. Please try again.");
      return;
    }
    setOpeningId(planId);
    setOpenError(null);
    try {
      const plan = await fetchPlan(planId);
      onOpenPlan(plan, summary);
      onClose();
    } catch {
      setOpenError("Couldn't open that plan. Please try again.");
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <ModalShell onClose={onClose} ariaLabel="Plan calendar">
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
            <button aria-label="Previous month" onClick={() => setMonthCursor(addMonthsISO(monthCursor, -1))} style={navBtn}>‹</button>
            <strong style={{ minWidth: isMobile ? 116 : 150, textAlign: "center" }}>
              {monthLabelOf(monthCursor)}
            </strong>
            <button aria-label="Next month" onClick={() => setMonthCursor(addMonthsISO(monthCursor, 1))} style={navBtn}>›</button>
            <button
              onClick={() => setMonthCursor(startOfMonthISO(todayISO()))}
              style={{ ...navBtn, minWidth: "auto", padding: "0 0.6rem", fontSize: "0.78rem" }}
            >
              Today
            </button>
          </div>
          <button aria-label="Close calendar" onClick={onClose} style={{ ...navBtn, fontSize: "1.15rem" }}>✕</button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "0.75rem 1rem 1.25rem" }}>
          {isLoading && <p style={{ color: "#6b7280" }}>Loading…</p>}

          {/* Desktop: month grid (chips click-to-open). Mobile falls back to the
              agenda list below — a 7-col grid is unusable at 375px. */}
          {!isMobile && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: "2px", marginBottom: "1rem" }}>
              {WEEKDAYS.map((w) => (
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
                      backgroundColor: inMonth ? "#fff" : "#fafbfc",
                      opacity: inMonth ? 1 : 0.5,
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                      overflow: "hidden",
                    }}
                  >
                    <span style={{ fontSize: "0.72rem", fontWeight: isToday ? 700 : 500, color: isToday ? "#2563eb" : "#374151", alignSelf: "flex-end" }}>
                      {dayOfMonth(date)}
                    </span>
                    {chips.map((c, i) => (
                      <button
                        key={`${c.plan_id}-${i}`}
                        onClick={() => handleOpen(c.plan_id)}
                        disabled={openingId === c.plan_id}
                        title={c.meals.join(", ") || `Plan #${c.plan_id}`}
                        style={chipStyle(c.status)}
                      >
                        {c.meals[0] ?? "Plan"}
                        {c.meals.length > 1 ? ` +${c.meals.length - 1}` : ""}
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

          {/* Actionable list: open a plan, or reschedule / unschedule its date.
              On mobile this is the whole calendar (agenda); on desktop it sits
              under the grid so the reschedule controls aren't crammed into cells. */}
          <div>
            {!isMobile && (
              <h4 style={{ margin: "0 0 0.5rem", fontSize: "0.88rem", color: "#374151" }}>
                Scheduled plans
              </h4>
            )}
            {!isLoading && plans.length === 0 && (
              <p style={{ color: "#6b7280", fontSize: "0.9rem", margin: 0 }}>
                No scheduled plans in {monthLabelOf(monthCursor)}. Give a plan a start date to see it here.
              </p>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
              {plans.map((p) => {
                const firstMeal = p.days.flatMap((d) => d.meals)[0];
                return (
                  <div
                    key={p.plan_id}
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: "0.5rem",
                      padding: "0.5rem 0.6rem",
                      border: "1px solid #e5e7eb",
                      borderRadius: 6,
                      backgroundColor: "#f9fafb",
                    }}
                  >
                    <span style={{ ...chipStyle(p.status), cursor: "default" }}>{p.status}</span>
                    <button
                      onClick={() => handleOpen(p.plan_id)}
                      disabled={openingId === p.plan_id}
                      style={{ background: "none", border: "none", color: "#1d4ed8", cursor: "pointer", fontWeight: 600, padding: 0, textAlign: "left", flex: 1, minWidth: 130 }}
                    >
                      {firstMeal ?? `Plan #${p.plan_id}`}
                      {p.days.length > 1 ? ` · ${p.days.length} days` : ""}
                    </button>
                    <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.8rem", color: "#374151" }}>
                      <span aria-hidden>📅</span>
                      {/* Uncontrolled + keyed on the server value: picking a new
                          date fires reschedule; when the refetch lands, the key
                          flips and the input remounts on the new date — no
                          snap-back flicker. */}
                      <input
                        key={p.start_date}
                        type="date"
                        aria-label={`Reschedule plan ${p.plan_id}`}
                        defaultValue={p.start_date}
                        onChange={(e) =>
                          rescheduleMutation.mutate({
                            planId: p.plan_id,
                            startDate: e.target.value || null,
                          })
                        }
                        style={{ padding: "0.2rem 0.3rem", fontSize: "0.8rem" }}
                      />
                    </label>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </ModalShell>
  );
}
