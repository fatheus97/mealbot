import { useAuth } from "../contexts/AuthContext";
import { useGeneratePlan } from "../hooks/useServerState";
import { usePreferencesStore } from "../store/usePreferencesStore";
import type { MealPlanRequest, DietType } from "../types";

export function MealPlanner() {
  const { userId } = useAuth();
  const generatePlanMutation = useGeneratePlan();

  // Bind to Global Zustand Store
  const {
    days, setDays,
    dietType, setDietType,
    mealsPerDay, setMealsPerDay,
    peopleCount, setPeopleCount,
    tastePreferences, setTastePreferences,
    avoidIngredients, setAvoidIngredients
  } = usePreferencesStore();

  const handleGenerate = () => {
    if (!userId) return;

    // Transform comma-separated string inputs into strict arrays for the API
    const parseList = (input: string) =>
      input.split(",").map((s) => s.trim()).filter((s) => s.length > 0);

    const request: MealPlanRequest = {
      // Notice we do NOT send the fridge array here.
      // A proper REST backend retrieves the fridge from the database using the user_id.
      ingredients: [],
      taste_preferences: parseList(tastePreferences),
      avoid_ingredients: parseList(avoidIngredients),
      diet_type: dietType === "" ? null : dietType,
      meals_per_day: mealsPerDay,
      people_count: peopleCount,
      past_meals: [], // Historical deduplication logic belongs on the backend
    };

    generatePlanMutation.mutate({ userId, days, request });
  };

  if (!userId) {
    return null; // Don't render the planner if logged out
  }

  return (
    <section style={{ marginBottom: "2rem", borderTop: "2px solid #eee", paddingTop: "2rem" }}>
      <h2>Meal Planner</h2>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", maxWidth: "600px", marginBottom: "1rem" }}>
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

      {generatePlanMutation.isError && (
        <div style={{ color: "red", marginTop: "1rem", padding: "1rem", border: "1px solid red" }}>
          <strong>Failed to generate plan:</strong> {generatePlanMutation.error.message}
        </div>
      )}

      {/* Plan Render Output */}
      {generatePlanMutation.data && (
        <div style={{ marginTop: "2rem", padding: "1rem", backgroundColor: "#f9f9f9", color: "#111", borderRadius: "8px" }}>
          <h3>Your Generated Plan</h3>
          {generatePlanMutation.data.days.map((dayPlan, idx) => (
             <div key={idx} style={{ marginBottom: "1.5rem" }}>
               <h4 style={{ borderBottom: "1px solid #ddd", paddingBottom: "0.5rem" }}>Day {idx + 1}</h4>
               {dayPlan.meals.map((meal, mealIdx) => (
                 <div key={mealIdx} style={{ marginLeft: "1rem", marginBottom: "1rem" }}>
                   <strong>{meal.meal_type.toUpperCase()}:</strong> {meal.name}

                   <div style={{ margin: "0.25rem 0", fontSize: "0.9em", color: "#444" }}>
                     <em>Ingredients:</em> {meal.ingredients?.map(ing => `${ing.name} (${ing.quantity_grams}g)`).join(", ")}
                   </div>

                   <ol style={{ marginTop: "0.25rem", fontSize: "0.9em", paddingLeft: "1.2rem" }}>
                     {meal.steps?.map((step, stepIdx) => (
                       <li key={stepIdx} style={{ marginBottom: "0.25rem" }}>{step}</li>
                     ))}
                   </ol>
                 </div>
               ))}
             </div>
          ))}
        </div>
      )}
    </section>
  );
}