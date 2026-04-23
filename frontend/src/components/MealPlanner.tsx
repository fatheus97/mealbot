import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useGeneratePlan, useRegeneratePlan, useConfirmPlan, useMealEntries, useCookMeal, useUncookMeal, useFinishPlan, useRateMeal, useFridge, useUserProfile } from "../hooks/useServerState";
import { StarRating } from "./StarRating";
import { IngredientChipInput } from "./IngredientChipInput";
import { DayLayoutEditor } from "./DayLayoutEditor";
import { usePreferencesStore } from "../store/usePreferencesStore";
import { mealTypeLabel, type MealType } from "../constants/mealTypes";
import type { MealPlanRequest, MealPlanResponse, MealPlanSummary, FrozenMeal, DietType } from "../types";

// Fallback seed for a single day when the user has no saved default layout.
// main_course is the least opinionated single-meal day; the editor lets the
// user add slots from there.
const FALLBACK_DAY: MealType[] = ["main_course"];

function resizeLayouts(
  current: MealType[][],
  targetLen: number,
  seed: MealType[],
): MealType[][] {
  if (current.length === targetLen) return current;
  if (current.length > targetLen) return current.slice(0, targetLen);
  const extra = Array.from({ length: targetLen - current.length }, () => [...seed]);
  return [...current, ...extra];
}

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
  const rateMutation = useRateMeal();

  // Derive initial state directly from the initialPlan prop. The parent
  // (App.tsx) remounts this component via `key={openedPlan?.plan.plan_id}`
  // when a different plan is opened, so prop→state sync via useEffect is
  // unnecessary and was flagged by react-hooks/set-state-in-effect.
  const [currentPlan, setCurrentPlan] = useState<MealPlanResponse | null>(initialPlan ?? null);
  const [frozenMeals, setFrozenMeals] = useState<Set<string>>(new Set());
  const [isConfirmed, setIsConfirmed] = useState(initialPlan != null);
  const [isFinished, setIsFinished] = useState(initialSummary?.finished_at != null);
  // Per-run only: intentionally not persisted in the preferences store —
  // "use these ingredients" is a one-shot hint for THIS plan generation.
  const [ingredientsToUse, setIngredientsToUse] = useState<string[]>([]);

  // Scroll the rendered plan into view when the component mounts with an
  // opened plan (via App.tsx's key-based remount on Open). We only scroll
  // on mount — not when the user generates a new plan on the same mount —
  // because that view is already at the form and a jump would be disorienting.
  const planContainerRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (initialPlan != null) {
      planContainerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [initialPlan]);

  const { data: fridgeItems } = useFridge(userId);
  const { data: profile } = useUserProfile(userId);
  const fridgeSuggestions = useMemo(
    () => (Array.isArray(fridgeItems) ? fridgeItems.map((i) => i.name) : []),
    [fridgeItems],
  );
  const userDefaultLayout: MealType[] = useMemo(
    () => (profile?.default_day_layout && profile.default_day_layout.length > 0
      ? profile.default_day_layout
      : FALLBACK_DAY),
    [profile],
  );

  // Per-day customization: off by default so the existing meals_per_day path
  // stays intact for users who haven't opted in. When toggled on, each day is
  // seeded from the user's default_day_layout (or the single-main_course
  // fallback if they haven't set one).
  const [customizeDays, setCustomizeDays] = useState(false);
  const [dayLayouts, setDayLayouts] = useState<MealType[][]>([]);
  const [expandedDays, setExpandedDays] = useState<Set<number>>(new Set([0]));

  const planId = currentPlan?.plan_id ?? null;
  const { data: mealEntries } = useMealEntries(isConfirmed ? planId : null);

  // Bind to Global Zustand Store
  const {
    days, setDays,
    dietType, setDietType,
    mealsPerDay, setMealsPerDay,
    peopleCount, setPeopleCount,
    tastePreferences, setTastePreferences,
    avoidIngredients, setAvoidIngredients,
    stockOnly, setStockOnly,
  } = usePreferencesStore();

  // Keep dayLayouts aligned with (days, userDefaultLayout) while per-day
  // customization is on. Uses the "adjust state while rendering" pattern
  // (same as DayLayoutEditor) so eslint's set-state-in-effect rule stays
  // happy and we avoid an extra commit per resize.
  //
  // syncedSeed tracks the seed we last populated with. Important for the
  // cold-load race: the user can toggle customize ON *before* the /users
  // fetch resolves, at which point userDefaultLayout is still FALLBACK_DAY.
  // When the profile lands, userDefaultLayout changes and we must re-seed
  // any un-grown days — otherwise the user silently gets main_course-only
  // days instead of their saved default. resizeLayouts only fills new
  // positions, so days the user has already touched are preserved.
  const [syncedDays, setSyncedDays] = useState(days);
  const [syncedCustomize, setSyncedCustomize] = useState(customizeDays);
  const [syncedSeed, setSyncedSeed] = useState<MealType[]>(userDefaultLayout);
  if (
    customizeDays &&
    (syncedDays !== days || !syncedCustomize || syncedSeed !== userDefaultLayout)
  ) {
    setSyncedDays(days);
    setSyncedCustomize(true);
    setSyncedSeed(userDefaultLayout);
    setDayLayouts((prev) => resizeLayouts(prev, days, userDefaultLayout));
  } else if (!customizeDays && syncedCustomize) {
    setSyncedCustomize(false);
  }

  const setDayLayoutAt = useCallback((idx: number, next: MealType[]) => {
    setDayLayouts((prev) => {
      const arr = [...prev];
      arr[idx] = next;
      return arr;
    });
  }, []);

  const toggleDayExpanded = useCallback((idx: number) => {
    setExpandedDays((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx); else next.add(idx);
      return next;
    });
  }, []);

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
      ingredients_to_use: ingredientsToUse,
      diet_type: dietType === "" ? null : dietType,
      meals_per_day: mealsPerDay,
      people_count: peopleCount,
      past_meals: [],
      stock_only: stockOnly,
      // Only send day_layouts when the user has opted into per-day
      // customization — otherwise backend falls back to user.default_day_layout
      // or the legacy meals_per_day path.
      day_layouts: customizeDays
        ? resizeLayouts(dayLayouts, days, userDefaultLayout)
        : null,
    };

    setCurrentPlan(null);
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
      onSuccess: () => {
        setIsConfirmed(true);
        // Freezing is only meaningful pre-confirm (as a regenerate hint).
        // Clear the set so the frozen-blue styling doesn't mask the
        // cooked-green styling on the same meal post-confirm.
        setFrozenMeals(new Set());
      },
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

  const handleRate = (dayIdx: number, mealIdx: number, rating: number) => {
    if (!planId) return;
    const entry = findEntry(dayIdx, mealIdx);
    if (!entry) return;
    rateMutation.mutate({ planId, mealEntryId: entry.id, rating });
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
            <option value="baby_food">Baby food (6–12 mo)</option>
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

        <label style={{ gridColumn: "span 2", display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={stockOnly}
            onChange={(e) => setStockOnly(e.target.checked)}
          />
          Use only stock ingredients (no shopping)
        </label>

        <label style={{ gridColumn: "span 2" }}>
          Taste Preferences (comma separated):
          <input type="text" value={tastePreferences} onChange={(e) => setTastePreferences(e.target.value)} placeholder="e.g. spicy, savory, Asian" style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label style={{ gridColumn: "span 2" }}>
          Ingredients to Avoid (comma separated):
          <input type="text" value={avoidIngredients} onChange={(e) => setAvoidIngredients(e.target.value)} placeholder="e.g. peanuts, cilantro" style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label style={{ gridColumn: "span 2" }}>
          Ingredients to use up (this run only):
          <IngredientChipInput
            values={ingredientsToUse}
            onChange={setIngredientsToUse}
            suggestions={fridgeSuggestions}
            placeholder="Type an ingredient and press Enter (fridge items auto-suggest)"
          />
        </label>

        <label style={{ gridColumn: "span 2", display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={customizeDays}
            onChange={(e) => setCustomizeDays(e.target.checked)}
          />
          Customize meal types per day
          <span style={{ fontSize: "0.8rem", color: "#666", marginLeft: "auto" }}>
            Off: uses "Meals per day" count · On: overrides per day
          </span>
        </label>

        {customizeDays && (
          <div style={{ gridColumn: "span 2", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {Array.from({ length: days }).map((_, dayIdx) => {
              const layout = dayLayouts[dayIdx] ?? userDefaultLayout;
              const expanded = expandedDays.has(dayIdx);
              return (
                <div
                  key={dayIdx}
                  style={{
                    border: "1px solid #ddd",
                    borderRadius: "6px",
                    padding: "0.5rem 0.75rem",
                    backgroundColor: "#fcfcfc",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => toggleDayExpanded(dayIdx)}
                    aria-expanded={expanded}
                    style={{
                      display: "flex",
                      width: "100%",
                      alignItems: "center",
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: 0,
                      fontSize: "0.95rem",
                    }}
                  >
                    <span style={{ marginRight: "0.4rem" }}>{expanded ? "▼" : "▶"}</span>
                    <strong>Day {dayIdx + 1}</strong>
                    <span style={{ marginLeft: "0.75rem", color: "#666", fontSize: "0.85rem" }}>
                      {layout.map((mt) => mealTypeLabel(mt)).join(" · ")}
                    </span>
                  </button>
                  {expanded && (
                    <div style={{ marginTop: "0.5rem" }}>
                      <DayLayoutEditor
                        value={layout}
                        onChange={(next) => setDayLayoutAt(dayIdx, next)}
                        ariaLabel={`Day ${dayIdx + 1} layout`}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
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
        <div ref={planContainerRef} style={{ marginTop: "2rem", padding: "1rem", backgroundColor: "#f9f9f9", color: "#111", borderRadius: "8px", overflowX: "auto", wordBreak: "break-word" }}>
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
                       <strong>{mealTypeLabel(meal.meal_type, meal.meal_type_label).toUpperCase()}:</strong> {meal.name}
                       {meal.total_time_minutes != null && (
                         <span
                           style={{ marginLeft: "0.5rem", fontSize: "0.85em", color: "#666" }}
                           aria-label={`Total time ${meal.total_time_minutes} minutes`}
                         >
                           · {meal.total_time_minutes} min
                         </span>
                       )}
                       {(isConfirmed || isFinished) && entry && (
                         <StarRating
                           rating={entry.rating}
                           onRate={(r) => handleRate(idx, mealIdx, r)}
                           disabled={isFinished}
                         />
                       )}
                     </div>

                     <div style={{ margin: "0.25rem 0", fontSize: "0.9em", color: "#444" }}>
                       <em>Ingredients:</em>{" "}
                       {[...(meal.ingredients ?? [])]
                         .sort((a, b) => (a.is_spice ? 1 : 0) - (b.is_spice ? 1 : 0))
                         .map((ing, i, arr) => (
                           <span key={i}>
                             {ing.is_spice
                               ? <span style={{ fontStyle: "italic" }}>{ing.name}</span>
                               : <span>{ing.name} ({ing.quantity_grams}g)</span>}
                             {i < arr.length - 1 ? ", " : ""}
                           </span>
                         ))}
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
