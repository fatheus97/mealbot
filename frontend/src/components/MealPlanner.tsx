import { useState, useCallback } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useGeneratePlan, useRegeneratePlan } from "../hooks/useServerState";
import { usePreferencesStore } from "../store/usePreferencesStore";
import type { MealPlanRequest, MealPlanResponse, FrozenMeal, DietType } from "../types";

export function MealPlanner() {
  const { userId } = useAuth();
  const generatePlanMutation = useGeneratePlan();
  const regenerateMutation = useRegeneratePlan();

  const [currentPlan, setCurrentPlan] = useState<MealPlanResponse | null>(null);
  const [frozenMeals, setFrozenMeals] = useState<Set<string>>(new Set());

  // Bind to Global Zustand Store
  const {
    days, setDays,
    dietType, setDietType,
    mealsPerDay, setMealsPerDay,
    peopleCount, setPeopleCount,
    tastePreferences, setTastePreferences,
    avoidIngredients, setAvoidIngredients
  } = usePreferencesStore();

  const toggleFreeze = useCallback((dayIdx: number, mealIdx: number) => {
    const key = `${dayIdx}-${mealIdx}`;
    setFrozenMeals((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const handleGenerate = () => {
    if (!userId) return;

    // Transform comma-separated string inputs into strict arrays for the API
    const parseList = (input: string) =>
      input.split(",").map((s) => s.trim()).filter((s) => s.length > 0);

    const request: MealPlanRequest = {
      ingredients: [],
      taste_preferences: parseList(tastePreferences),
      avoid_ingredients: parseList(avoidIngredients),
      diet_type: dietType === "" ? null : dietType,
      meals_per_day: mealsPerDay,
      people_count: peopleCount,
      past_meals: [],
    };

    setFrozenMeals(new Set());
    generatePlanMutation.mutate({ userId, days, request }, {
      onSuccess: (data) => setCurrentPlan(data),
    });
  };

  const handleRegenerate = () => {
    if (!currentPlan?.plan_id) return;

    const frozen: FrozenMeal[] = [];
    frozenMeals.forEach((key) => {
      const [d, m] = key.split("-").map(Number);
      frozen.push({ day_index: d, meal_index: m });
    });

    regenerateMutation.mutate(
      { planId: currentPlan.plan_id, request: { frozen_meals: frozen } },
      { onSuccess: (data) => setCurrentPlan(data) },
    );
  };

  if (!userId) {
    return null; // Don't render the planner if logged out
  }

  return (
    <section style={{ marginBottom: "2rem", borderTop: "2px solid #eee", paddingTop: "2rem" }}>
      <h2>Meal Planner</h2>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
        <label>
          Days to plan:
          <input type="number" value={days} onChange={(e) => setDays(Number(e.target.value) || 1)} min={1} max={7} style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label>
          Diet Type:
          <select
            value={dietType}
            onChange={(e) => setDietType(e.target.value as DietType | "")}
            style={{ width: "100%", marginTop: "0.25rem" }}
          >
            <option value="">(None)</option>
            <option value="balanced">Balanced</option>
            <option value="high_protein">High Protein</option>
            <option value="low_carb">Low Carb</option>
            <option value="vegetarian">Vegetarian</option>
            <option value="vegan">Vegan</option>
          </select>
        </label>

        <label>
          Meals per day:
          <input type="number" value={mealsPerDay} onChange={(e) => setMealsPerDay(Number(e.target.value) || 1)} min={1} max={5} style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label>
          People count:
          <input type="number" value={peopleCount} onChange={(e) => setPeopleCount(Number(e.target.value) || 1)} min={1} max={10} style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label style={{ gridColumn: "span 2" }}>
          Taste Preferences (comma separated):
          <input type="text" value={tastePreferences} onChange={(e) => setTastePreferences(e.target.value)} placeholder="e.g. spicy, savory, Asian" style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label style={{ gridColumn: "span 2" }}>
          Ingredients to Avoid (comma separated):
          <input type="text" value={avoidIngredients} onChange={(e) => setAvoidIngredients(e.target.value)} placeholder="e.g. peanuts, cilantro" style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>
      </div>

      <button onClick={handleGenerate} disabled={generatePlanMutation.isPending} style={{ padding: "0.5rem 2rem", fontSize: "1.1rem" }}>
        {generatePlanMutation.isPending ? "Generating Plan (This takes a moment)..." : "Generate Plan"}
      </button>

      {(generatePlanMutation.isError || regenerateMutation.isError) && (
        <div style={{ color: "red", marginTop: "1rem", padding: "1rem", border: "1px solid red" }}>
          <strong>Error:</strong> {(generatePlanMutation.error ?? regenerateMutation.error)?.message}
        </div>
      )}

      {/* Plan Render Output */}
      {currentPlan && (
        <div style={{ marginTop: "2rem", padding: "1rem", backgroundColor: "#f9f9f9", color: "#111", borderRadius: "8px", overflowX: "auto", wordBreak: "break-word" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h3 style={{ margin: 0 }}>Your Generated Plan</h3>
            {frozenMeals.size > 0 && (
              <button
                onClick={handleRegenerate}
                disabled={regenerateMutation.isPending}
                style={{ padding: "0.4rem 1.2rem", fontSize: "0.95rem", backgroundColor: "#4a90d9", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
              >
                {regenerateMutation.isPending ? "Regenerating..." : "Regenerate Unfrozen"}
              </button>
            )}
          </div>
          {frozenMeals.size > 0 && (
            <p style={{ fontSize: "0.85em", color: "#666", margin: "0 0 1rem 0" }}>
              {frozenMeals.size} meal(s) frozen. Unfrozen meals will be regenerated.
            </p>
          )}
          {currentPlan.days.map((dayPlan, idx) => (
             <div key={idx} style={{ marginBottom: "1.5rem" }}>
               <h4 style={{ borderBottom: "1px solid #ddd", paddingBottom: "0.5rem" }}>Day {idx + 1}</h4>
               {dayPlan.meals.map((meal, mealIdx) => {
                 const isFrozen = frozenMeals.has(`${idx}-${mealIdx}`);
                 return (
                   <div
                     key={mealIdx}
                     style={{
                       marginLeft: "1rem",
                       marginBottom: "1rem",
                       padding: "0.5rem",
                       borderLeft: isFrozen ? "3px solid #4a90d9" : "3px solid transparent",
                       backgroundColor: isFrozen ? "#eef4fb" : "transparent",
                       borderRadius: "4px",
                     }}
                   >
                     <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                       <button
                         onClick={() => toggleFreeze(idx, mealIdx)}
                         title={isFrozen ? "Unfreeze this meal" : "Freeze this meal"}
                         style={{
                           background: "none",
                           border: "1px solid #ccc",
                           borderRadius: "4px",
                           padding: "0.15rem 0.4rem",
                           cursor: "pointer",
                           fontSize: "0.85rem",
                           color: isFrozen ? "#4a90d9" : "#888",
                         }}
                       >
                         {isFrozen ? "Frozen" : "Freeze"}
                       </button>
                       <strong>{meal.meal_type.toUpperCase()}:</strong> {meal.name}
                     </div>

                     <div style={{ margin: "0.25rem 0", fontSize: "0.9em", color: "#444" }}>
                       <em>Ingredients:</em> {meal.ingredients?.map(ing => `${ing.name} (${ing.quantity_grams}g)`).join(", ")}
                     </div>

                     <ol style={{ marginTop: "0.25rem", fontSize: "0.9em", paddingLeft: "1.2rem" }}>
                       {meal.steps?.map((step, stepIdx) => (
                         <li key={stepIdx} style={{ marginBottom: "0.25rem" }}>{step}</li>
                       ))}
                     </ol>
                   </div>
                 );
               })}
             </div>
          ))}
          {currentPlan.shopping_list.length > 0 && (
            <div style={{ marginTop: "1.5rem", padding: "1rem", backgroundColor: "#fff", border: "1px solid #ddd", borderRadius: "6px" }}>
              <h4 style={{ margin: "0 0 0.75rem 0" }}>Shopping List</h4>
              <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.9em" }}>
                {currentPlan.shopping_list.map((item, i) => (
                  <li key={i} style={{ marginBottom: "0.25rem" }}>
                    {item.name} — {Math.round(item.quantity_grams)}g
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}