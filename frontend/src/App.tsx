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
import type { MealPlanResponse, MealPlanSummary } from "./types";

interface OpenedPlan {
  plan: MealPlanResponse;
  summary: MealPlanSummary;
}

function MainLayout() {
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
      <h1 style={{ borderBottom: "2px solid #333", paddingBottom: "0.5rem" }}>🤖 Mealbot Planner</h1>
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
  const { userId } = useAuth();
  // Remounts the entire authenticated subtree when the active user changes,
  // so no component-local state from a previous session survives login/logout.
  return <MainLayout key={userId ?? "anon"} />;
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
