import { useState } from "react";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { useIsMobile } from "./hooks/useIsMobile";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AuthBar } from "./components/AuthBar";
import { DemoBanner } from "./components/DemoBanner";
import { Fridge } from "./components/Fridge";
import { PlanCatalog } from "./components/PlanCatalog";
import { MealPlanner } from "./components/MealPlanner";
import { OnboardingModal } from "./components/OnboardingModal";
import { CookbookFab } from "./components/CookbookFab";
import { AdminDashboard } from "./components/admin/AdminDashboard";
import type { MealPlanResponse, MealPlanSummary } from "./types";

interface OpenedPlan {
  plan: MealPlanResponse;
  summary: MealPlanSummary;
}

function MainLayout({ onOpenAdmin }: { onOpenAdmin?: () => void }) {
  const { userId, onboardingCompleted, isDemo } = useAuth();
  const isMobile = useIsMobile();
  // openedPlan and other component-local state in this subtree are scoped to a
  // single user session — see AuthRoot below for the userId-keyed remount that
  // discards them on logout/login transitions.
  const [openedPlan, setOpenedPlan] = useState<OpenedPlan | null>(null);

  // Extra bottom padding on mobile so the last rows can scroll clear of the
  // fixed CookbookFab (bottom-right) instead of hiding under it.
  const padding = isMobile
    ? isDemo
      ? "48px 0.75rem 5rem"
      : "1.25rem 0.75rem 5rem"
    : isDemo
      ? "52px 1rem 2rem"
      : "2rem 1rem";

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding, fontFamily: "sans-serif" }}>
      <DemoBanner />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.5rem",
          borderBottom: "2px solid #333",
          paddingBottom: "0.5rem",
        }}
      >
        <h1 style={{ margin: 0 }}>🤖 Mealbot Planner</h1>
        {onOpenAdmin && (
          <button
            onClick={onOpenAdmin}
            style={{
              padding: "0.35rem 0.75rem",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "#fff",
              color: "#111827",
              cursor: "pointer",
              fontSize: 14,
              whiteSpace: "nowrap",
            }}
          >
            🛠️ Admin
          </button>
        )}
      </div>
      <AuthBar />
      <Fridge />
      <PlanCatalog onOpenPlan={(plan, summary) => setOpenedPlan({ plan, summary })} />
      <MealPlanner
        key={openedPlan?.plan.plan_id ?? "new"}
        initialPlan={openedPlan?.plan ?? null}
        initialSummary={openedPlan?.summary}
        onExitPlan={() => setOpenedPlan(null)}
      />
      {userId && !onboardingCompleted && !isDemo && <OnboardingModal />}
      {userId && <CookbookFab />}
    </div>
  );
}

function AuthRoot() {
  const { userId, isAdmin } = useAuth();
  const [view, setView] = useState<"main" | "admin">("main");
  const [seenUserId, setSeenUserId] = useState<number | null>(userId);
  // Reset the view whenever the active user changes (login / logout / switch).
  // `view` lives here (not keyed to userId), so without this a force-logout that
  // happened while in the admin view would carry `view="admin"` into the next
  // session and drop the next admin straight onto the dashboard. Adjusting state
  // during render (the React "reset on prop change" pattern) re-renders
  // immediately with the corrected view — no flash.
  if (userId !== seenUserId) {
    setSeenUserId(userId);
    setView("main");
  }
  // The `&& isAdmin` guard also means a logout (isAdmin → false) drops out of the
  // admin view immediately.
  if (view === "admin" && isAdmin) {
    return <AdminDashboard key={userId ?? "anon"} onExit={() => setView("main")} />;
  }
  return (
    <MainLayout
      key={userId ?? "anon"}
      onOpenAdmin={isAdmin ? () => setView("admin") : undefined}
    />
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <AuthRoot />
      </AuthProvider>
    </ErrorBoundary>
  );
}
