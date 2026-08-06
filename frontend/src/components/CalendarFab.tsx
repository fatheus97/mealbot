import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { PlanCalendar } from "./PlanCalendar";
import type { MealPlanResponse, MealPlanSummary } from "../types";
import { useI18n } from "../i18n";

interface CalendarFabProps {
  onOpenPlan: (plan: MealPlanResponse, summary: MealPlanSummary) => void;
}

// Floating calendar button, fixed bottom-right, stacked ABOVE the CookbookFab
// (which sits at bottom:1.5rem and is 56px tall). Blue so it reads as distinct
// from the brown 📖 cookbook button at a glance.
export function CalendarFab({ onOpenPlan }: CalendarFabProps) {
  const { t } = useI18n();
  const { userId } = useAuth();
  const [open, setOpen] = useState(false);

  if (!userId) return null;

  return (
    <>
      <button
        type="button"
        aria-label={t("fab.openCalendar")}
        onClick={() => setOpen(true)}
        style={{
          position: "fixed",
          // Stack above the cookbook FAB: its bottom (1.5rem) + height (56px) + a gap.
          bottom: "calc(1.5rem + 56px + 0.75rem)",
          right: "1.5rem",
          width: "56px",
          height: "56px",
          borderRadius: "50%",
          backgroundColor: "#2563eb",
          color: "white",
          border: "none",
          fontSize: "1.6rem",
          cursor: "pointer",
          boxShadow: "0 4px 14px rgba(0,0,0,0.25)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 50,
        }}
      >
        📅
      </button>

      {open && <PlanCalendar onClose={() => setOpen(false)} onOpenPlan={onOpenPlan} />}
    </>
  );
}
