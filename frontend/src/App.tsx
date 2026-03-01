import { AuthProvider } from "./contexts/AuthContext";
import { AuthBar } from "./components/AuthBar";
import { Fridge } from "./components/Fridge";
import { MealPlanner } from "./components/MealPlanner";

function MainLayout() {
  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "2rem 1rem", fontFamily: "sans-serif" }}>
      <h1 style={{ borderBottom: "2px solid #333", paddingBottom: "0.5rem" }}>🤖 Mealbot Planner</h1>
      <AuthBar />
      <Fridge />
      <MealPlanner />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <MainLayout />
    </AuthProvider>
  );
}