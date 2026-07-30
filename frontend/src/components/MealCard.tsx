import { FavoriteStar } from "./FavoriteStar";
import { IngredientsList } from "./recipe/IngredientsList";
import { RecipeSteps } from "./recipe/RecipeSteps";
import { MealEditor } from "./recipe/MealEditor";
import { CookMode } from "./recipe/CookMode";
import { useReopenTarget } from "../contexts/CookTimerContext";
import { mealTypeLabel } from "../constants/mealTypes";
import { LEFTOVER_SHORT_LABEL } from "../utils/leftovers";
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
  // Resolved provenance for a leftover, e.g.
  // "Sun Jul 19 · Hot dinner — Chicken curry". null for an ordinary meal AND
  // for a leftover whose source can't be resolved — the card degrades to a
  // bare marker rather than breaking.
  leftoverSource?: string | null;
  // Drives the compact badge; the full label stays in `title`.
  isMobile?: boolean;
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
  leftoverSource = null,
  isMobile = false,
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
  // A leftover is identified by the LINK, never by an empty ingredient list —
  // an ordinary meal could legitimately have no ingredients.
  const isLeftover = meal.leftover_of != null;

  // Whether cook mode may be entered for this meal at all. Named because the
  // floating timer bubble routes back in through the SAME gate: a timer can
  // outlive the state that allowed it (mark the meal cooked, or finish the
  // plan, while it counts down), and the bubble must not reopen cook mode for
  // a meal that no longer offers "Start cooking".
  const canStartCooking =
    isConfirmed && !isFinished && !!entry && !isCooked && !isLeftover && (meal.steps?.length ?? 0) > 0;
  useReopenTarget(cookStorageKey, onStartCooking, canStartCooking);

  // Explicit precedence instead of a fourth nested ternary. Cooked wins (it is
  // the most recent fact about the meal), then frozen (an active user choice),
  // then leftover (a static property).
  const accent = isCooked
    ? { border: "#16a34a", bg: "#f0fdf4" }
    : isFrozen
      ? { border: "#4a90d9", bg: "#eef4fb" }
      : isLeftover
        ? { border: "#a78bfa", bg: "#f5f3ff" }
        : { border: "transparent", bg: "transparent" };

  return (
    <div
      style={{
        marginLeft: "1rem",
        marginBottom: "1rem",
        padding: "0.5rem",
        borderLeft: `3px solid ${accent.border}`,
        backgroundColor: accent.bg,
        borderRadius: "4px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
        {/* Freezing is hidden on a leftover: the server freezes a link group
            atomically (source + its leftovers together), so a per-meal toggle
            here would imply control the user doesn't have. Freeze the source
            instead and the leftover follows. */}
        {!isConfirmed && !isLeftover && (
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
        {/* Gated on isLeftover EXPLICITLY, not on steps.length. A leftover has
            a reheat step, so a length check would let cook mode open and write
            progress under cookmode:${planId}:${day}:${meal} for a meal that
            isn't being cooked. Marking it cooked via the Cook button is still
            correct and stays available. */}
        {canStartCooking && !isEditing && !isCooking && (
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
        {isLeftover && (
          // Explicit color paired with the background — the card sits on
          // MealPlanner's light surface, but this badge carries its own pair so
          // it stays legible if it's ever reused elsewhere.
          // Short form on mobile: the full label eats a whole line at 375px
          // next to four buttons, and the header row already wraps.
          <span
            title={leftoverSource ? `Leftovers from ${leftoverSource}` : "Leftovers"}
            style={{
              marginLeft: "0.4rem",
              padding: "0.1rem 0.45rem",
              borderRadius: "10px",
              fontSize: "0.75rem",
              fontWeight: 600,
              backgroundColor: "#ede9fe",
              color: "#5b21b6",
              whiteSpace: "nowrap",
            }}
          >
            {isMobile || !leftoverSource
              ? LEFTOVER_SHORT_LABEL
              : `↻ Leftovers from ${leftoverSource}`}
          </span>
        )}
        {meal.total_time_minutes != null && (
          <span
            style={{ marginLeft: "0.5rem", fontSize: "0.85em", color: "#666" }}
            aria-label={`Total time ${meal.total_time_minutes} minutes`}
          >
            · {meal.total_time_minutes} min
          </span>
        )}
        {entry && (
          // Disabled — not hidden — on a leftover. The backend 422s a favorite
          // on one (a content-free "reheat of X" embedded in the global RAG
          // corpus would be served back to future generations as a proven
          // recipe with no ingredients), and useFavoriteMeal has no onError, so
          // an enabled star would be a control that silently never works.
          // Disabling with an explanation is better than removing it: the star
          // is present on every other meal, so its absence would just look like
          // a bug.
          <FavoriteStar
            isFavorite={entry.is_favorite}
            onToggle={onFavoriteToggle}
            disabled={favoritePending || isLeftover}
            title={
              isLeftover
                ? "Leftovers can't be saved to the cookbook — star the original meal instead"
                : undefined
            }
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
          {/* A leftover has no ingredients of its own — they were bought and
              cooked with the source meal — so an empty "Ingredients:" list
              would read as a bug. Say where the food came from instead. */}
          {isLeftover ? (
            <div style={{ margin: "0.25rem 0", fontSize: "0.9em", color: "#444" }}>
              <em>
                {leftoverSource
                  ? `Uses leftovers from ${leftoverSource} — nothing extra to buy.`
                  : "Uses leftovers from an earlier meal — nothing extra to buy."}
              </em>
            </div>
          ) : (
            <div style={{ margin: "0.25rem 0", fontSize: "0.9em", color: "#444" }}>
              <em>Ingredients:</em>{" "}
              <IngredientsList ingredients={meal.ingredients ?? []} />
            </div>
          )}

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
