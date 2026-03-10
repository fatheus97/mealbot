import { useState, useCallback, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useGeneratePlan, useRegeneratePlan, useConfirmPlan, useMealEntries, useCookMeal, useUncookMeal, useFinishPlan } from "../hooks/useServerState";
import { usePreferencesStore } from "../store/usePreferencesStore";
import type { MealPlanRequest, MealPlanResponse, MealPlanSummary, FrozenMeal, DietType } from "../types";

interface MealPlannerProps {
  initialPlan?: MealPlanResponse | null;
  initialSummary?: MealPlanSummary;
}

export function MealPlanner({ initialPlan, initialSummary }: MealPlannerProps) {
  const { userId } = useAuth();
  const generatePlanMutation = useGeneratePlan();
  const regenerateMutation = useRegeneratePlan();
  const confirmMutation = useConfirmPlan();
  const cookMutation = useCookMeal();
  const uncookMutation = useUncookMeal();
  const finishMutation = useFinishPlan();

  const [currentPlan, setCurrentPlan] = useState<MealPlanResponse | null>(null);
  const [frozenMeals, setFrozenMeals] = useState<Set<string>>(new Set());
  const [isConfirmed, setIsConfirmed] = useState(false);
  const [isFinished, setIsFinished] = useState(false);

  // Sync initialPlan prop to currentPlan state (catalog plans are always confirmed)
  useEffect(() => {
    if (initialPlan) {
      setCurrentPlan(initialPlan);
      setFrozenMeals(new Set());
      setIsConfirmed(true);
      setIsFinished(initialSummary?.finished_at != null);
    }
  }, [initialPlan, initialSummary]);

  const planId = currentPlan?.plan_id ?? null;
  const { data: mealEntries } = useMealEntries(isConfirmed ? planId : null);

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
    setIsConfirmed(false);
    setIsFinished(false);
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

  const handleConfirm = () => {
    if (!currentPlan?.plan_id) return;
    confirmMutation.mutate(currentPlan.plan_id, {
      onSuccess: () => setIsConfirmed(true),
    });
  };

  const handleFinish = () => {
    if (!planId) return;
    finishMutation.mutate(planId, {
      onSuccess: () => setIsFinished(true),
    });
  };

  // Find the meal entry for a given day/meal index (1-based in entries, 0-based in UI)
  const findEntry = (dayIdx: number, mealIdx: number) => {
    if (!mealEntries) return null;
    return mealEntries.find(
      (e) => e.day_index === dayIdx + 1 && e.meal_index === mealIdx + 1
    ) ?? null;
  };

  const handleCookToggle = (dayIdx: number, mealIdx: number) => {
    if (!planId) return;
    const entry = findEntry(dayIdx, mealIdx);
    if (!entry) return;

    if (entry.cooked_at) {
      uncookMutation.mutate({ planId, mealEntryId: entry.id });
    } else {
      cookMutation.mutate({ planId, mealEntryId: entry.id });
    }
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
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <h3 style={{ margin: 0 }}>
                {isFinished ? "Finished Plan" : isConfirmed ? "Confirmed Plan" : "Your Generated Plan"}
              </h3>
              {isFinished && (
                <span style={{
                  padding: "0.15rem 0.6rem", borderRadius: "12px", fontSize: "0.8rem",
                  fontWeight: 600, backgroundColor: "#f3e8ff", color: "#7c3aed",
                }}>
                  Finished
                </span>
              )}
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              {!isConfirmed && frozenMeals.size > 0 && (
                <button
                  onClick={handleRegenerate}
                  disabled={regenerateMutation.isPending}
                  style={{ padding: "0.4rem 1.2rem", fontSize: "0.95rem", backgroundColor: "#4a90d9", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                >
                  {regenerateMutation.isPending ? "Regenerating..." : "Regenerate Unfrozen"}
                </button>
              )}
              {!isConfirmed && (
                <button
                  onClick={handleConfirm}
                  disabled={confirmMutation.isPending}
                  style={{ padding: "0.4rem 1.2rem", fontSize: "0.95rem", backgroundColor: "#16a34a", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                >
                  {confirmMutation.isPending ? "Confirming..." : "Confirm Plan"}
                </button>
              )}
              {isConfirmed && !isFinished && (
                <button
                  onClick={handleFinish}
                  disabled={finishMutation.isPending}
                  style={{ padding: "0.4rem 1.2rem", fontSize: "0.95rem", backgroundColor: "#7c3aed", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                >
                  {finishMutation.isPending ? "Finishing..." : "Finish Plan"}
                </button>
              )}
            </div>
          </div>
          {!isConfirmed && frozenMeals.size > 0 && (
            <p style={{ fontSize: "0.85em", color: "#666", margin: "0 0 1rem 0" }}>
              {frozenMeals.size} meal(s) frozen. Unfrozen meals will be regenerated.
            </p>
          )}
          {currentPlan.days.map((dayPlan, idx) => (
             <div key={idx} style={{ marginBottom: "1.5rem" }}>
               <h4 style={{ borderBottom: "1px solid #ddd", paddingBottom: "0.5rem" }}>Day {idx + 1}</h4>
               {dayPlan.meals.map((meal, mealIdx) => {
                 const isFrozen = frozenMeals.has(`${idx}-${mealIdx}`);
                 const entry = findEntry(idx, mealIdx);
                 const isCooked = entry?.cooked_at != null;
                 return (
                   <div
                     key={mealIdx}
                     style={{
                       marginLeft: "1rem",
                       marginBottom: "1rem",
                       padding: "0.5rem",
                       borderLeft: isFrozen ? "3px solid #4a90d9" : isCooked ? "3px solid #16a34a" : "3px solid transparent",
                       backgroundColor: isFrozen ? "#eef4fb" : isCooked ? "#f0fdf4" : "transparent",
                       borderRadius: "4px",
                     }}
                   >
                     <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                       {!isConfirmed && (
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
                       )}
                       {isConfirmed && !isFinished && entry && (
                         <button
                           onClick={() => handleCookToggle(idx, mealIdx)}
                           disabled={cookMutation.isPending || uncookMutation.isPending}
                           title={isCooked ? "Mark as not cooked" : "Mark as cooked"}
                           style={{
                             background: "none",
                             border: `1px solid ${isCooked ? "#16a34a" : "#ccc"}`,
                             borderRadius: "4px",
                             padding: "0.15rem 0.4rem",
                             cursor: "pointer",
                             fontSize: "0.85rem",
                             color: isCooked ? "#16a34a" : "#888",
                           }}
                         >
                           {isCooked ? "Cooked" : "Cook"}
                         </button>
                       )}
                       {isFinished && entry && (
                         <span style={{
                           fontSize: "0.85rem",
                           color: isCooked ? "#16a34a" : "#888",
                           fontStyle: "italic",
                         }}>
                           {isCooked ? "Cooked" : "Not cooked"}
                         </span>
                       )}
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
