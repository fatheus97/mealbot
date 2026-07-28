import { useMemo, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useReopenTarget } from "../contexts/CookTimerContext";
import { useIsMobile } from "../hooks/useIsMobile";
import {
  useFridge,
  useGenerateRecipe,
  useCookRecipe,
  useFavoriteRecipe,
  useRemoveFromCookbook,
} from "../hooks/useServerState";
import { IngredientChipInput } from "./IngredientChipInput";
import { FavoriteStar } from "./FavoriteStar";
import { IngredientsList } from "./recipe/IngredientsList";
import { RecipeSteps } from "./recipe/RecipeSteps";
import { MealEditor } from "./recipe/MealEditor";
import { CookMode } from "./recipe/CookMode";
import {
  MEAL_TYPES,
  MEAL_TYPE_LABELS,
  mealTypeLabel,
  type MealType,
} from "../constants/mealTypes";
import { DietarySelector } from "./DietarySelector";
import type {
  Allergen,
  CookRecipeRequest,
  DietType,
  PlannedMeal,
  SingleRecipeRequest,
} from "../types";

// Cook Now has a single transient recipe on screen, so one fixed cook-mode
// storage key is enough — it's cleared whenever a new recipe is generated or
// once a cook succeeds.
const COOKNOW_COOK_KEY = "cookmode:cooknow";

// Cook Now: one-shot single-recipe generator. The saved recipe carries its
// full PlannedMeal through /recipe/cook so the server doesn't re-invoke the
// LLM on the cook action — it just persists + debits fridge + marks cooked.
export function CookNowForm() {
  const { userId } = useAuth();
  const isMobile = useIsMobile();
  const { data: fridgeItems } = useFridge(userId);
  const generateMutation = useGenerateRecipe();
  const cookMutation = useCookRecipe();
  const favoriteRecipeMutation = useFavoriteRecipe();
  const removeFromCookbookMutation = useRemoveFromCookbook();

  const fridgeSuggestions = useMemo(
    () => (Array.isArray(fridgeItems) ? fridgeItems.map((i) => i.name) : []),
    [fridgeItems],
  );

  const [mealType, setMealType] = useState<MealType>("main_course");
  const [dietTypes, setDietTypes] = useState<DietType[]>([]);
  const [allergens, setAllergens] = useState<Allergen[]>([]);
  const [peopleCount, setPeopleCount] = useState(2);
  const [tastePreferences, setTastePreferences] = useState("");
  const [avoidIngredients, setAvoidIngredients] = useState<string[]>([]);
  const [ingredientsToUse, setIngredientsToUse] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [stockOnly, setStockOnly] = useState(false);

  const [recipe, setRecipe] = useState<PlannedMeal | null>(null);
  // Inline editor open on the generated recipe. Only offered before the recipe
  // is cooked or saved — editing local state after either would silently
  // diverge from the persisted MealEntry.
  const [editing, setEditing] = useState(false);
  // Real-time cooking checklist open on the generated recipe.
  const [cooking, setCooking] = useState(false);
  // Registered only while this form is mounted. It lives behind a tab
  // (`{effectiveMode === "cook_now" && <CookNowForm />}`), so switching to Plan
  // Ahead unmounts it — after which the bubble must stop offering a way back
  // rather than rendering a button whose handler is bound to a dead instance.
  useReopenTarget(COOKNOW_COOK_KEY, () => setCooking(true), recipe != null);
  // Track the request that produced `recipe` so /recipe/cook gets the same
  // context (server re-validates meal_type match). Resetting the form while
  // a recipe is on screen keeps the old pendingRequest until a new generate.
  const [pendingRequest, setPendingRequest] = useState<SingleRecipeRequest | null>(null);
  // The machine_generation id for the recipe on screen. Echoed back on
  // cook/favorite so the server can link any edits to what was generated.
  // Stays fixed across inline edits — the edit IS the delta we want to capture.
  const [generationId, setGenerationId] = useState<number | null>(null);
  const [cookedEntry, setCookedEntry] = useState<{ id: number; name: string } | null>(null);
  // Once the user stars a generated recipe, the server returns a meal_entry_id
  // and we treat the recipe as "saved." Subsequent star toggles route through
  // the plan-side /favorite endpoint by id rather than re-creating a row.
  const [savedEntry, setSavedEntry] = useState<{ id: number; isFavorite: boolean } | null>(null);

  if (!userId) return null;

  const parseList = (input: string) =>
    input.split(",").map((s) => s.trim()).filter((s) => s.length > 0);

  const buildRequest = (): SingleRecipeRequest => ({
    meal_type: mealType,
    diet_types: dietTypes,
    allergens,
    people_count: peopleCount,
    taste_preferences: parseList(tastePreferences),
    avoid_ingredients: avoidIngredients,
    ingredients_to_use: ingredientsToUse,
    stock_only: stockOnly,
    note: note.trim() ? note.trim() : null,
  });

  const handleGenerate = () => {
    const req = buildRequest();
    setRecipe(null);
    setGenerationId(null);
    setCookedEntry(null);
    setSavedEntry(null);
    setEditing(false);
    setCooking(false);
    // Drop any half-finished checklist from a previous recipe.
    try {
      localStorage.removeItem(COOKNOW_COOK_KEY);
    } catch {
      // ignore — storage unavailable
    }
    setPendingRequest(req);
    generateMutation.mutate(req, {
      onSuccess: (data) => {
        setRecipe(data.recipe);
        setGenerationId(data.generation_id);
      },
    });
  };

  const handleCook = () => {
    if (!recipe || !pendingRequest) return;
    const payload: CookRecipeRequest = { ...pendingRequest, recipe, generation_id: generationId };
    cookMutation.mutate(payload, {
      onSuccess: (entry) => {
        setCookedEntry({ id: entry.id, name: entry.name });
        // Cooking creates its own MealEntry (kind="cook_now"). If the user
        // already starred (and we have a savedEntry), the cooked row is a
        // separate entry — the saved one keeps its own state.
        if (!savedEntry) {
          setSavedEntry({ id: entry.id, isFavorite: entry.is_favorite });
        }
        // Close cook mode + drop its saved checklist only now that the server
        // confirmed — a failed cook leaves the overlay open for a retry.
        setCooking(false);
        try {
          localStorage.removeItem(COOKNOW_COOK_KEY);
        } catch {
          // ignore
        }
      },
    });
  };

  // Cookbook toggle on the in-memory Cook Now recipe.
  //
  //  * First star → POST /recipe/favorite creates the MealEntry, returns id.
  //  * Un-star    → DELETE /cookbook/{id} clears the bit + embedding.
  //  * Re-star    → POST /recipe/favorite again, which is a fresh insert.
  //                 We accept that "star → unstar → star" produces a new
  //                 row rather than reviving the old one; the cookbook
  //                 listing dedupes nothing, but the user paid for both
  //                 stars deliberately so it's their cookbook.
  const handleFavoriteToggle = (next: boolean) => {
    if (!recipe) return;
    if (next) {
      favoriteRecipeMutation.mutate(
        { meal_type: mealType, people_count: peopleCount, recipe, generation_id: generationId },
        { onSuccess: (entry) => setSavedEntry({ id: entry.id, isFavorite: true }) },
      );
    } else if (savedEntry) {
      // Clear savedEntry entirely (not just isFavorite:false): the DELETE
      // removed the MealEntry row, so there's nothing to diverge from — this
      // restores the Edit affordance and lets a re-star create a fresh row.
      removeFromCookbookMutation.mutate(savedEntry.id, {
        onSuccess: () => setSavedEntry(null),
      });
    }
  };

  const isFavorited = savedEntry?.isFavorite ?? false;
  const favoritePending = favoriteRecipeMutation.isPending || removeFromCookbookMutation.isPending;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <p style={{ margin: 0, color: "#555" }}>
        Generate one recipe for what you're cooking right now. Mark it cooked
        to debit the fridge — no shopping list, no multi-day planning.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: "1rem" }}>
        <label>
          Meal type
          <select
            value={mealType}
            onChange={(e) => setMealType(e.target.value as MealType)}
            style={{ width: "100%", marginTop: "0.25rem", padding: "0.4rem" }}
          >
            {MEAL_TYPES.map((mt) => (
              <option key={mt} value={mt}>{MEAL_TYPE_LABELS[mt]}</option>
            ))}
          </select>
        </label>

        <label>
          People
          <input
            type="number"
            value={peopleCount}
            onChange={(e) => setPeopleCount(Number(e.target.value) || 1)}
            min={1}
            max={10}
            style={{ width: "100%", marginTop: "0.25rem", padding: "0.4rem" }}
          />
        </label>

        <div style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          <DietarySelector
            dietTypes={dietTypes}
            allergens={allergens}
            onToggleDiet={(d) =>
              setDietTypes((prev) =>
                prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d],
              )
            }
            onToggleAllergen={(a) =>
              setAllergens((prev) =>
                prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a],
              )
            }
          />
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={stockOnly}
            onChange={(e) => setStockOnly(e.target.checked)}
          />
          Only use what's in the fridge
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          Taste preferences (comma separated)
          <input
            type="text"
            value={tastePreferences}
            onChange={(e) => setTastePreferences(e.target.value)}
            placeholder="e.g. spicy, light, Mediterranean"
            style={{ width: "100%", marginTop: "0.25rem", padding: "0.4rem" }}
          />
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          Ingredients to avoid
          <IngredientChipInput
            values={avoidIngredients}
            onChange={setAvoidIngredients}
            suggestions={[]}
            placeholder="Type an ingredient to avoid and press Enter"
          />
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          Ingredients to feature
          <IngredientChipInput
            values={ingredientsToUse}
            onChange={setIngredientsToUse}
            suggestions={fridgeSuggestions}
            placeholder="Type an ingredient and press Enter"
          />
        </label>

        <label style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
          Note (optional)
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. pasta-based, quick, use up cilantro"
            maxLength={200}
            style={{ width: "100%", marginTop: "0.25rem", padding: "0.4rem" }}
          />
        </label>
      </div>

      <button
        type="button"
        onClick={handleGenerate}
        disabled={generateMutation.isPending}
        style={{
          alignSelf: "flex-start",
          padding: "0.5rem 1.5rem",
          fontSize: "1rem",
          backgroundColor: "#2563eb",
          color: "white",
          border: "none",
          borderRadius: "6px",
          cursor: generateMutation.isPending ? "not-allowed" : "pointer",
        }}
      >
        {generateMutation.isPending ? "Generating…" : "Generate recipe"}
      </button>

      {generateMutation.isError && (
        <div role="alert" style={{ color: "#b91c1c", border: "1px solid #fca5a5", padding: "0.5rem", borderRadius: "4px" }}>
          {generateMutation.error?.message ?? "Failed to generate recipe."}
        </div>
      )}

      {recipe && (
        <div
          style={{
            padding: "1rem",
            backgroundColor: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: "8px",
            color: "#111",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", flex: 1 }}>
              <div style={{ paddingTop: "1.4rem" }}>
                <FavoriteStar
                  isFavorite={isFavorited}
                  onToggle={handleFavoriteToggle}
                  disabled={favoritePending}
                />
              </div>
              <div>
                <strong style={{ textTransform: "uppercase", color: "#6b7280", fontSize: "0.85rem" }}>
                  {mealTypeLabel(recipe.meal_type, recipe.meal_type_label)}
                </strong>
                <h3 style={{ margin: "0.25rem 0 0.5rem 0" }}>{recipe.name}</h3>
                {recipe.total_time_minutes != null && (
                  <span style={{ fontSize: "0.9rem", color: "#6b7280" }}>
                    {recipe.total_time_minutes} min
                  </span>
                )}
              </div>
            </div>
            {editing || cooking ? null : cookedEntry ? (
              <span style={{ color: "#16a34a", fontWeight: 600 }}>✓ Cooked</span>
            ) : (
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
                {!savedEntry && (
                  <button
                    type="button"
                    onClick={() => setEditing(true)}
                    style={{
                      padding: "0.5rem 1rem",
                      backgroundColor: "#fff",
                      color: "#374151",
                      border: "1px solid #d1d5db",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    Edit
                  </button>
                )}
                {recipe.steps.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      cookMutation.reset(); // clear any prior cook error so it can't bleed into this session
                      setEditing(false);
                      setCooking(true);
                    }}
                    style={{
                      padding: "0.5rem 1rem",
                      backgroundColor: "#fff",
                      color: "#16a34a",
                      border: "1px solid #16a34a",
                      borderRadius: "6px",
                      cursor: "pointer",
                    }}
                  >
                    Start cooking
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCook}
                  disabled={cookMutation.isPending}
                  style={{
                    padding: "0.5rem 1.25rem",
                    backgroundColor: "#16a34a",
                    color: "white",
                    border: "none",
                    borderRadius: "6px",
                    cursor: cookMutation.isPending ? "not-allowed" : "pointer",
                  }}
                >
                  {cookMutation.isPending ? "Saving…" : "Mark as cooked"}
                </button>
              </div>
            )}
          </div>

          {editing ? (
            <div style={{ marginTop: "0.75rem" }}>
              <MealEditor
                meal={recipe}
                onSave={(updated) => {
                  setRecipe(updated);
                  setEditing(false);
                }}
                onCancel={() => setEditing(false)}
              />
            </div>
          ) : (
            <>
              <div style={{ marginTop: "0.75rem" }}>
                <em>Ingredients:</em>{" "}
                <IngredientsList ingredients={recipe.ingredients} />
              </div>

              <RecipeSteps steps={recipe.steps} />
            </>
          )}

          {/* Fullscreen cooking overlay (portals to <body>). */}
          {cooking && (
            <CookMode
              meal={recipe}
              storageKey={COOKNOW_COOK_KEY}
              onDone={handleCook}
              onClose={() => setCooking(false)}
              doneLabel="Mark as cooked"
              donePending={cookMutation.isPending}
              doneError={
                cookMutation.isError
                  ? "Couldn't save — check your connection and try again."
                  : null
              }
            />
          )}

          {cookMutation.isError && (
            <div role="alert" style={{ color: "#b91c1c", marginTop: "0.5rem" }}>
              {cookMutation.error?.message ?? "Failed to save recipe."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
