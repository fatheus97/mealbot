import { useState, useCallback, useMemo, useRef, useEffect, type CSSProperties } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import { useGeneratePlan, useRegeneratePlan, useConfirmPlan, useUnconfirmPlan, useMealEntries, useCookMeal, useUncookMeal, useFinishPlan, useReopenPlan, useFavoriteMeal, useUpdateMeal, useFridge, useUserProfile } from "../hooks/useServerState";
import { MealCard } from "./MealCard";
import { IngredientChipInput } from "./IngredientChipInput";
import { DayLayoutEditor } from "./DayLayoutEditor";
import { CookNowForm } from "./CookNowForm";
import { usePreferencesStore } from "../store/usePreferencesStore";
import { mealTypeLabel, type MealType } from "../constants/mealTypes";
import type { MealPlanRequest, MealPlanResponse, MealPlanSummary, FrozenMeal, DietType, PlannedMeal, IngredientAmount } from "../types";
import { todayISO, dayDateLabel } from "../utils/planDates";
import { leftoverSourceLabel } from "../utils/leftovers";

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

// Plain-text render of the shopping list for clipboard / share export, e.g.
// "Eggs — 200g\nMilk — 500g". Empty string when there's nothing to export so
// callers can bail without emitting a blank clipboard entry.
function shoppingListToText(items: IngredientAmount[] | undefined): string {
  if (!items || items.length === 0) return "";
  return items.map((i) => `${i.name} — ${Math.round(i.quantity_grams)}g`).join("\n");
}

// Explicit light-surface buttons for the shopping-list card. The card is on the
// plan-output surface (which pins its own light background + dark text), so
// light-styled controls with an explicit colour stay legible in both OS colour
// schemes — per .claude/rules/frontend.md (set a colour whenever you set a bg).
const shoppingListBtn: CSSProperties = {
  padding: "0.3rem 0.7rem",
  fontSize: "0.8rem",
  border: "1px solid #cbd5e1",
  borderRadius: 6,
  background: "#fff",
  color: "#111",
  cursor: "pointer",
};

interface MealPlannerProps {
  initialPlan?: MealPlanResponse | null;
  initialSummary?: MealPlanSummary;
  // Invoked when the user switches mode while viewing an opened plan, so
  // the parent can clear openedPlan and MealPlanner remounts cleanly with
  // no initialPlan. Optional so the non-opened path works without a prop.
  onExitPlan?: () => void;
}

export function MealPlanner({ initialPlan, initialSummary, onExitPlan }: MealPlannerProps) {
  const { userId } = useAuth();
  const isMobile = useIsMobile();
  const generatePlanMutation = useGeneratePlan();
  const regenerateMutation = useRegeneratePlan();
  const confirmMutation = useConfirmPlan();
  const unconfirmMutation = useUnconfirmPlan();
  const cookMutation = useCookMeal();
  const uncookMutation = useUncookMeal();
  const finishMutation = useFinishPlan();
  const reopenMutation = useReopenPlan();
  const favoriteMutation = useFavoriteMeal();
  const updateMealMutation = useUpdateMeal();

  // Which meal (if any) is currently open in the inline editor, keyed by
  // "day-meal" (0-based, matching the render indices).
  const [editingMeal, setEditingMeal] = useState<string | null>(null);
  // Which meal (if any) is open in real-time cooking mode, same "day-meal" key.
  const [cookingMeal, setCookingMeal] = useState<string | null>(null);

  // Derive initial state directly from the initialPlan prop. The parent
  // (App.tsx) remounts this component via `key={openedPlan?.plan.plan_id}`
  // when a different plan is opened, so prop→state sync via useEffect is
  // unnecessary and was flagged by react-hooks/set-state-in-effect.
  const [currentPlan, setCurrentPlan] = useState<MealPlanResponse | null>(initialPlan ?? null);
  // Calendar start date (YYYY-MM-DD) sent at generation and confirm. A fresh
  // plan defaults to today; an opened plan seeds from its own scheduled date.
  const [startDate, setStartDate] = useState<string>(initialPlan?.start_date ?? todayISO());
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

  // Shopping-list check-off (ephemeral — index-keyed, reset whenever the list
  // changes) plus the transient "Copied ✓" affordance for the copy button.
  const [checkedItems, setCheckedItems] = useState<Set<number>>(new Set());
  const [copiedList, setCopiedList] = useState(false);
  // Web Share is feature-detected, NOT gated on mobile: a capable desktop
  // browser should get the Share button too, and unsupported contexts simply
  // fall back to the always-present Copy button.
  const canShareList = typeof navigator.share === "function";

  // Clear the "Copied ✓" label a moment after a copy. A timer side-effect
  // (not prop→state sync), so an effect is the right tool here.
  useEffect(() => {
    if (!copiedList) return;
    const timer = setTimeout(() => setCopiedList(false), 1500);
    return () => clearTimeout(timer);
  }, [copiedList]);

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
    mode, setMode,
  } = usePreferencesStore();

  // When the user opens an existing plan (initialPlan passed in), force the
  // Plan Ahead tab so the rendered plan view is visible — a Cook Now tab
  // wouldn't render the opened plan at all.
  //
  // The tabs stay interactive even while viewing an opened plan: a click on
  // either one calls onExitPlan to dismiss the plan and land on that mode's
  // entry screen. That includes clicking the currently-highlighted Plan
  // Ahead tab, which deliberately resets to a fresh form rather than being a
  // no-op — the tab semantically means "go to the plan form", and the user's
  // only way out of an opened plan via the bar is to click a tab.
  const effectiveMode = initialPlan != null ? "plan_ahead" : mode;

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
    setCheckedItems(new Set());
    setIsConfirmed(false);
    setIsFinished(false);
    generatePlanMutation.mutate({ userId, days, startDate, request }, {
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
      {
        onSuccess: (data) => {
          setCurrentPlan(data);
          // A regenerated plan is a new shopping list, so drop stale ticks —
          // an index must never point at a different item than the user
          // checked off.
          setCheckedItems(new Set());
        },
      },
    );
  };

  // Shopping-list check-off + export (frontend-only; ticks live in component
  // state, never the backend).
  const toggleShoppingItem = (i: number) => {
    setCheckedItems((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  const copyShoppingList = () => {
    const text = shoppingListToText(currentPlan?.shopping_list);
    if (!text) return;
    // Best-effort — optional chaining short-circuits the whole chain (incl.
    // .then) when the Clipboard API is unavailable, so this never throws.
    void navigator.clipboard?.writeText(text).then(
      () => setCopiedList(true),
      () => undefined,
    );
  };

  const shareShoppingList = () => {
    const text = shoppingListToText(currentPlan?.shopping_list);
    if (!text) return;
    // Only reachable from a button rendered when navigator.share exists.
    // Swallow rejections, including the user dismissing the share sheet.
    void navigator.share({ title: "Shopping List", text }).catch(() => undefined);
  };

  const handleConfirm = () => {
    if (!currentPlan?.plan_id) return;
    confirmMutation.mutate({ planId: currentPlan.plan_id, startDate }, {
      onSuccess: () => {
        setIsConfirmed(true);
        // Sync currentPlan.start_date with what confirm persisted, so the
        // confirmed-plan day headers (which switch to reading currentPlan once
        // isConfirmed) match the server: a real date overrides; a cleared date
        // ("" -> null) is a no-op that keeps the existing date — mirroring the
        // backend confirm semantics.
        setCurrentPlan((prev) =>
          prev ? { ...prev, start_date: startDate || prev.start_date } : prev,
        );
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

  const handleUnconfirm = () => {
    if (!planId) return;
    unconfirmMutation.mutate(planId, {
      onSuccess: () => setIsConfirmed(false),
    });
  };

  const handleReopen = () => {
    if (!planId) return;
    reopenMutation.mutate(planId, {
      onSuccess: () => setIsFinished(false),
    });
  };

  // Find the meal entry for a given day/meal index (1-based in entries, 0-based in UI)
  const findEntry = (dayIdx: number, mealIdx: number) => {
    if (!mealEntries) return null;
    return mealEntries.find(
      (e) => e.day_index === dayIdx + 1 && e.meal_index === mealIdx + 1
    ) ?? null;
  };

  const handleFavoriteToggle = (dayIdx: number, mealIdx: number, next: boolean) => {
    if (!planId) return;
    const entry = findEntry(dayIdx, mealIdx);
    if (!entry) return;
    favoriteMutation.mutate({ planId, mealEntryId: entry.id, isFavorite: next });
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

  const handleSaveEdit = (dayIdx: number, mealIdx: number, updated: PlannedMeal) => {
    if (!currentPlan?.plan_id) return;
    updateMealMutation.mutate(
      {
        planId: currentPlan.plan_id,
        dayIndex: dayIdx,
        mealIndex: mealIdx,
        body: {
          name: updated.name,
          ingredients: updated.ingredients,
          steps: updated.steps,
          total_time_minutes: updated.total_time_minutes ?? null,
        },
      },
      {
        onSuccess: (serverMeal) => {
          // Replace the edited meal in local plan state with the server's
          // canonical version (echoes back preserved meal_type etc.).
          setCurrentPlan((prev) =>
            prev
              ? {
                  ...prev,
                  days: prev.days.map((d, di) =>
                    di === dayIdx
                      ? { ...d, meals: d.meals.map((m, mi) => (mi === mealIdx ? serverMeal : m)) }
                      : d,
                  ),
                }
              : prev,
          );
          setEditingMeal(null);
        },
      },
    );
  };

  // Finish real-time cooking: mark the meal cooked (idempotent). Cook mode is
  // closed and its saved progress cleared only after the mutation succeeds — a
  // failed request keeps the overlay open for a retry.
  const handleFinishCooking = (dayIdx: number, mealIdx: number) => {
    if (!planId) return;
    const entry = findEntry(dayIdx, mealIdx);
    if (!entry) return;
    const finish = () => {
      try {
        localStorage.removeItem(`cookmode:${planId}:${dayIdx}:${mealIdx}`);
      } catch {
        // ignore
      }
      setCookingMeal(null);
    };
    // Close cook mode + drop its saved progress only after the cook mutation
    // succeeds — a failed request keeps the overlay open for a retry. An
    // already-cooked meal just closes.
    if (entry.cooked_at) {
      finish();
    } else {
      cookMutation.mutate({ planId, mealEntryId: entry.id }, { onSuccess: finish });
    }
  };

  if (!userId) {
    return null; // Don't render the planner if logged out
  }

  return (
    <section style={{ marginBottom: "2rem", borderTop: "2px solid #eee", paddingTop: "2rem" }}>
      <h2>Meal Planner</h2>

      <div role="tablist" style={{ display: "flex", gap: "0.25rem", marginBottom: "1rem", borderBottom: "2px solid #e5e7eb" }}>
        <button
          type="button"
          role="tab"
          aria-selected={effectiveMode === "cook_now"}
          onClick={() => {
            setMode("cook_now");
            if (initialPlan != null) onExitPlan?.();
          }}
          style={{
            padding: "0.5rem 1.25rem",
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: "1rem",
            fontWeight: effectiveMode === "cook_now" ? 600 : 400,
            borderBottom: effectiveMode === "cook_now" ? "2px solid #2563eb" : "2px solid transparent",
            marginBottom: "-2px",
            color: effectiveMode === "cook_now" ? "#2563eb" : "#4b5563",
          }}
        >
          Cook Now
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={effectiveMode === "plan_ahead"}
          onClick={() => {
            setMode("plan_ahead");
            if (initialPlan != null) onExitPlan?.();
          }}
          style={{
            padding: "0.5rem 1.25rem",
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: "1rem",
            fontWeight: effectiveMode === "plan_ahead" ? 600 : 400,
            borderBottom: effectiveMode === "plan_ahead" ? "2px solid #2563eb" : "2px solid transparent",
            marginBottom: "-2px",
            color: effectiveMode === "plan_ahead" ? "#2563eb" : "#4b5563",
          }}
        >
          Plan Ahead
        </button>
      </div>

      {effectiveMode === "cook_now" && <CookNowForm />}

      {effectiveMode === "plan_ahead" && (<>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
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

        <label style={{ gridColumn: isMobile ? "auto" : "span 2", display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={stockOnly}
            onChange={(e) => setStockOnly(e.target.checked)}
          />
          Use only stock ingredients (no shopping)
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          Taste Preferences (comma separated):
          <input type="text" value={tastePreferences} onChange={(e) => setTastePreferences(e.target.value)} placeholder="e.g. spicy, savory, Asian" style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          Ingredients to Avoid (comma separated):
          <input type="text" value={avoidIngredients} onChange={(e) => setAvoidIngredients(e.target.value)} placeholder="e.g. peanuts, cilantro" style={{ width: "100%", marginTop: "0.25rem" }} />
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          Ingredients to use up (this run only):
          <IngredientChipInput
            values={ingredientsToUse}
            onChange={setIngredientsToUse}
            suggestions={fridgeSuggestions}
            placeholder="Type an ingredient and press Enter (fridge items auto-suggest)"
          />
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2", display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
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
          <div style={{ gridColumn: isMobile ? "auto" : "span 2", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
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
                    {dayDateLabel(startDate, dayIdx) && (
                      <span style={{ marginLeft: "0.5rem", color: "#666", fontSize: "0.85rem", fontWeight: 400 }}>
                        {dayDateLabel(startDate, dayIdx)}
                      </span>
                    )}
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

      {/* Start date — Day 1 maps to this real-world date. No explicit text
          colour on the label so it stays legible in both themes (it sits on the
          adaptive page background, not an explicit surface). */}
      <div style={{ marginBottom: "1rem", display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
        <label htmlFor="plan-start-date" style={{ fontSize: "1rem" }}>
          Start date
        </label>
        <input
          id="plan-start-date"
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          style={{ padding: "0.35rem 0.5rem", fontSize: "1rem" }}
        />
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
              {/*
                Defensive default: hide Un-confirm until mealEntries has
                actually loaded. `?? true` would flash the button on a
                freshly-opened stale plan (mealEntries undefined) and let
                the user click into a backend 409 if a meal turns out to
                be cooked. The brief flash-of-no-button right after a
                fresh confirm is harmless — entries fetch resolves in <1s.
              */}
              {isConfirmed && !isFinished && (mealEntries?.every((e) => e.cooked_at == null) ?? false) && (
                <button
                  onClick={handleUnconfirm}
                  disabled={unconfirmMutation.isPending}
                  title="Restore the fridge debit and return to the editable plan view"
                  style={{ padding: "0.4rem 1.2rem", fontSize: "0.95rem", backgroundColor: "#6b7280", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                >
                  {unconfirmMutation.isPending ? "Un-confirming..." : "Un-confirm"}
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
              {isFinished && (
                <button
                  onClick={handleReopen}
                  disabled={reopenMutation.isPending}
                  title="Re-debit ingredients for uncooked meals and return to the active plan"
                  style={{ padding: "0.4rem 1.2rem", fontSize: "0.95rem", backgroundColor: "#6b7280", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                >
                  {reopenMutation.isPending ? "Reopening..." : "Reopen"}
                </button>
              )}
            </div>
          </div>
          {(unconfirmMutation.isError || reopenMutation.isError) && (
            <div role="alert" style={{ color: "#b91c1c", marginBottom: "1rem", padding: "0.5rem 0.75rem", backgroundColor: "#fef2f2", border: "1px solid #fecaca", borderRadius: "4px", fontSize: "0.9rem" }}>
              {(unconfirmMutation.error ?? reopenMutation.error)?.message}
            </div>
          )}
          {!isConfirmed && frozenMeals.size > 0 && (
            <p style={{ fontSize: "0.85em", color: "#666", margin: "0 0 1rem 0" }}>
              {frozenMeals.size} meal(s) frozen. Unfrozen meals will be regenerated.
            </p>
          )}
          {currentPlan.days.map((dayPlan, idx) => (
             <div key={idx} style={{ marginBottom: "1.5rem" }}>
               <h4 style={{ borderBottom: "1px solid #ddd", paddingBottom: "0.5rem" }}>
                 Day {idx + 1}
                 {/* Pre-confirm, the date follows the (editable) Start-date field
                     so the preview updates live; once confirmed or viewing an
                     opened plan, it reads the server value on currentPlan (which
                     handleConfirm keeps in sync) so an edit to the field can't
                     misrepresent a plan whose date is already committed. */}
                 {dayDateLabel(isConfirmed ? currentPlan.start_date : startDate, idx) && (
                   <span style={{ marginLeft: "0.6rem", color: "#666", fontSize: "0.85rem", fontWeight: 400 }}>
                     {dayDateLabel(isConfirmed ? currentPlan.start_date : startDate, idx)}
                   </span>
                 )}
               </h4>
               {dayPlan.meals.map((meal, mealIdx) => {
                 const isFrozen = frozenMeals.has(`${idx}-${mealIdx}`);
                 const entry = findEntry(idx, mealIdx);
                 const isCooked = entry?.cooked_at != null;
                 const isEditing = editingMeal === `${idx}-${mealIdx}`;
                 const isCooking = cookingMeal === `${idx}-${mealIdx}`;
                 return (
                   <MealCard
                     key={mealIdx}
                     meal={meal}
                     entry={entry}
                     isFrozen={isFrozen}
                     isCooked={isCooked}
                     isEditing={isEditing}
                     isCooking={isCooking}
                     isConfirmed={isConfirmed}
                     isFinished={isFinished}
                     // SAME start-date expression as the day header above, or
                     // the badge and the header disagree while the user is
                     // editing the date pre-confirm.
                     leftoverSource={leftoverSourceLabel(
                       currentPlan,
                       meal.leftover_of,
                       isConfirmed ? currentPlan.start_date : startDate,
                     )}
                     isMobile={isMobile}
                     cookStorageKey={`cookmode:${planId}:${idx}:${mealIdx}`}
                     cookTogglePending={cookMutation.isPending || uncookMutation.isPending}
                     cookPending={cookMutation.isPending}
                     favoritePending={favoriteMutation.isPending}
                     savePending={updateMealMutation.isPending}
                     saveError={
                       updateMealMutation.isError
                         ? (updateMealMutation.error?.message ?? "Save failed")
                         : null
                     }
                     cookFailed={cookMutation.isError}
                     onToggleFreeze={() => toggleFreeze(idx, mealIdx)}
                     onCookToggle={() => handleCookToggle(idx, mealIdx)}
                     onStartEdit={() => setEditingMeal(`${idx}-${mealIdx}`)}
                     onCancelEdit={() => setEditingMeal(null)}
                     onSave={(updated) => handleSaveEdit(idx, mealIdx, updated)}
                     onStartCooking={() => {
                       cookMutation.reset(); // clear any prior cook error so it can't bleed into this session
                       setEditingMeal(null);
                       setCookingMeal(`${idx}-${mealIdx}`);
                     }}
                     onStopCooking={() => setCookingMeal(null)}
                     onFinishCooking={() => handleFinishCooking(idx, mealIdx)}
                     onFavoriteToggle={(next) => handleFavoriteToggle(idx, mealIdx, next)}
                   />
                 );
               })}
             </div>
          ))}
          {currentPlan.shopping_list.length > 0 && (
            <div style={{ marginTop: "1.5rem", padding: "1rem", backgroundColor: "#fff", color: "#111", border: "1px solid #ddd", borderRadius: "6px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
                <h4 style={{ margin: 0 }}>Shopping List</h4>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    type="button"
                    onClick={copyShoppingList}
                    aria-label="Copy shopping list"
                    style={{ ...shoppingListBtn, minWidth: "5.5rem" }}
                  >
                    {copiedList ? "Copied ✓" : "Copy"}
                  </button>
                  {canShareList && (
                    <button
                      type="button"
                      onClick={shareShoppingList}
                      aria-label="Share shopping list"
                      style={shoppingListBtn}
                    >
                      Share
                    </button>
                  )}
                </div>
              </div>
              <ul style={{ margin: 0, padding: 0, listStyle: "none", fontSize: "0.9em" }}>
                {currentPlan.shopping_list.map((item, i) => {
                  const checked = checkedItems.has(i);
                  return (
                    <li key={i} style={{ marginBottom: "0.25rem" }}>
                      <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleShoppingItem(i)}
                          aria-label={`Mark ${item.name} as bought`}
                        />
                        <span style={{ textDecoration: checked ? "line-through" : "none", color: checked ? "#9ca3af" : "inherit" }}>
                          {item.name} — {Math.round(item.quantity_grams)}g
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}
      </>)}
    </section>
  );
}
