import { FavoriteStar } from "./FavoriteStar";
import { IngredientsList } from "./recipe/IngredientsList";
import { RecipeSteps } from "./recipe/RecipeSteps";
import { MealEditor } from "./recipe/MealEditor";
import { CookMode } from "./recipe/CookMode";
import { mealTypeLabel } from "../constants/mealTypes";
import type { MealEntrySummary, PlannedMeal } from "../types";

// One meal inside a rendered plan: the action row (freeze / cook / edit /
// start-cooking / favorite), the ingredients+steps body (or the inline editor),
// and the fullscreen cooking overlay.
//
// Extracted verbatim from MealPlanner's nested day→meal map, which had grown to
// ~150 lines of inline JSX inside a closure. All plan state stays in the parent;
// this component is presentational and takes pre-bound callbacks, so it never
// needs to know its own day/meal indices.
//
// NOTE: this file is 100% inline styles like the rest of the app (CSS `@media`
// can't reach them — see .claude/rules/frontend.md). The card renders inside
// MealPlanner's explicit light surface (`#f9f9f9` / `#111`), so the hardcoded
// dark text here is safe *in that context* — don't lift these styles to a
// component that renders on the adaptive page background.
interface MealCardProps {
  meal: PlannedMeal;
  // The persisted meal row; null pre-confirm (entries only exist once the
  // plan is confirmed). Its presence gates cook/favorite affordances.
  entry: MealEntrySummary | null;
  isFrozen: boolean;
  isCooked: boolean;
  isEditing: boolean;
  isCooking: boolean;
  isConfirmed: boolean;
  isFinished: boolean;
  // localStorage key for cook-mode progress, owned by the parent so the
  // plan/day/meal coordinates stay in one place.
  cookStorageKey: string;

  // Deliberately two flags, not one: the Cook/Cooked toggle disables while
  // EITHER direction is in flight, but cook-mode's "Mark as cooked" button
  // only ever fires the cook mutation. Collapsing them would disable the
  // overlay's button during an unrelated uncook.
  cookTogglePending: boolean;
  cookPending: boolean;
  favoritePending: boolean;
  savePending: boolean;
  saveError: string | null;
  cookFailed: boolean;

  onToggleFreeze: () => void;
  onCookToggle: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: (updated: PlannedMeal) => void;
  onStartCooking: () => void;
  onStopCooking: () => void;
  onFinishCooking: () => void;
  onFavoriteToggle: (next: boolean) => void;
}

export function MealCard({
  meal,
  entry,
  isFrozen,
  isCooked,
  isEditing,
  isCooking,
  isConfirmed,
  isFinished,
  cookStorageKey,
  cookTogglePending,
  cookPending,
  favoritePending,
  savePending,
  saveError,
  cookFailed,
  onToggleFreeze,
  onCookToggle,
  onStartEdit,
  onCancelEdit,
  onSave,
  onStartCooking,
  onStopCooking,
  onFinishCooking,
  onFavoriteToggle,
}: MealCardProps) {
  return (
    <div
      style={{
        marginLeft: "1rem",
        marginBottom: "1rem",
        padding: "0.5rem",
        borderLeft: isFrozen ? "3px solid #4a90d9" : isCooked ? "3px solid #16a34a" : "3px solid transparent",
        backgroundColor: isFrozen ? "#eef4fb" : isCooked ? "#f0fdf4" : "transparent",
        borderRadius: "4px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
        {!isConfirmed && (
          <button
            onClick={onToggleFreeze}
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
        {isConfirmed && !isFinished && entry && !isCooking && (
          <button
            onClick={onCookToggle}
            disabled={cookTogglePending}
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
        {!isEditing && !isFinished && !isCooking && (
          <button
            onClick={onStartEdit}
            title="Edit this recipe"
            style={{
              background: "none",
              border: "1px solid #ccc",
              borderRadius: "4px",
              padding: "0.15rem 0.4rem",
              cursor: "pointer",
              fontSize: "0.85rem",
              color: "#555",
            }}
          >
            Edit
          </button>
        )}
        {isConfirmed && !isFinished && entry && !isCooked && !isEditing && !isCooking && (meal.steps?.length ?? 0) > 0 && (
          <button
            onClick={onStartCooking}
            title="Cook this recipe step by step"
            style={{
              background: "none",
              border: "1px solid #16a34a",
              borderRadius: "4px",
              padding: "0.15rem 0.4rem",
              cursor: "pointer",
              fontSize: "0.85rem",
              color: "#16a34a",
            }}
          >
            Start cooking
          </button>
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
        {entry && (
          <FavoriteStar
            isFavorite={entry.is_favorite}
            onToggle={onFavoriteToggle}
            disabled={favoritePending}
          />
        )}
      </div>

      {isEditing ? (
        <MealEditor
          meal={meal}
          onSave={onSave}
          onCancel={onCancelEdit}
          saving={savePending}
          error={saveError}
        />
      ) : (
        <>
          <div style={{ margin: "0.25rem 0", fontSize: "0.9em", color: "#444" }}>
            <em>Ingredients:</em>{" "}
            <IngredientsList ingredients={meal.ingredients ?? []} />
          </div>

          <div style={{ fontSize: "0.9em" }}>
            <RecipeSteps steps={meal.steps ?? []} />
          </div>
        </>
      )}
      {/* Fullscreen cooking overlay (portals to <body>). */}
      {isCooking && entry && (
        <CookMode
          meal={meal}
          storageKey={cookStorageKey}
          onDone={onFinishCooking}
          onClose={onStopCooking}
          doneLabel="Mark as cooked"
          donePending={cookPending}
          doneError={
            cookFailed
              ? "Couldn't mark as cooked — check your connection and try again."
              : null
          }
        />
      )}
    </div>
  );
}
