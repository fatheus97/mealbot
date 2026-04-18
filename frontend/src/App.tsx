import { useState } from "react";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AuthBar } from "./components/AuthBar";
import { DemoBanner } from "./components/DemoBanner";
import { Fridge } from "./components/Fridge";
import { PlanCatalog } from "./components/PlanCatalog";
import { MealPlanner } from "./components/MealPlanner";
import { OnboardingModal } from "./components/OnboardingModal";
import type { MealPlanResponse, MealPlanSummary } from "./types";

interface OpenedPlan {
  plan: MealPlanResponse;
  summary: MealPlanSummary;
}

function MainLayout() {
  const { userId, onboardingCompleted, isDemo } = useAuth();
  const [openedPlan, setOpenedPlan] = useState<OpenedPlan | null>(null);

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: isDemo ? "52px 1rem 2rem" : "2rem 1rem", fontFamily: "sans-serif" }}>
      <DemoBanner />
      <h1 style={{ borderBottom: "2px solid #333", paddingBottom: "0.5rem" }}>🤖 Mealbot Planner</h1>
      <AuthBar />
      <Fridge />
      <PlanCatalog onOpenPlan={(plan, summary) => setOpenedPlan({ plan, summary })} />
      <MealPlanner
        initialPlan={openedPlan?.plan ?? null}
        initialSummary={openedPlan?.summary}
      />
      {userId && !onboardingCompleted && !isDemo && <OnboardingModal />}
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <MainLayout />
      </AuthProvider>
    </ErrorBoundary>
  );
}
