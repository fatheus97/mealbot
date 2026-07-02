import { useRef, useState } from "react";
import type { IngredientAmount, PlannedMeal } from "../../types";
import { mealTypeLabel } from "../../constants/mealTypes";

interface Props {
  meal: PlannedMeal;
  // Receives the fully-edited meal with meal_type / meal_type_label carried
  // through unchanged. The parent decides persistence: the Plan Ahead view
  // PATCHes it to the server; Cook Now just updates local state.
  onSave: (updated: PlannedMeal) => void;
  onCancel: () => void;
  saving?: boolean;
  error?: string | null;
}

// Rows carry a stable `_key` so React keys survive add/remove. With index
// keys, removing a middle row makes React reuse DOM nodes by position, which
// yanks focus to the wrong input. `_key` is stripped before onSave.
type IngredientRow = IngredientAmount & { _key: number };
type StepRow = { _key: number; value: string };

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.35rem",
  boxSizing: "border-box",
};

const smallBtn: React.CSSProperties = {
  background: "none",
  border: "1px solid #ccc",
  borderRadius: "4px",
  padding: "0.15rem 0.5rem",
  cursor: "pointer",
  fontSize: "0.85rem",
};

// Editable form for a single meal's content (name, time, ingredients, steps).
// Reusable across the Plan Ahead result view and the Cook Now preview.
// meal_type / meal_type_label are NOT editable — the backend edit endpoint
// preserves the slot, so we carry them through untouched.
export function MealEditor({ meal, onSave, onCancel, saving = false, error = null }: Props) {
  const [name, setName] = useState(meal.name);
  const [time, setTime] = useState<string>(
    meal.total_time_minutes != null ? String(meal.total_time_minutes) : "",
  );
  // Seed row keys from index (deterministic — no ref read during render). New
  // rows draw from a monotonic counter bumped only in the add handlers (event
  // context). Keys need only be unique within each list, and the counter starts
  // past both seed ranges, so a new row can't collide with an existing key.
  const [ingredients, setIngredients] = useState<IngredientRow[]>(() =>
    meal.ingredients.map((ing, idx) => ({ ...ing, _key: idx })),
  );
  const [steps, setSteps] = useState<StepRow[]>(() =>
    meal.steps.map((s, idx) => ({ _key: idx, value: s })),
  );
  const nextKey = useRef(Math.max(meal.ingredients.length, meal.steps.length));

  const setIngredientAt = (key: number, patch: Partial<IngredientAmount>) =>
    setIngredients((prev) => prev.map((ing) => (ing._key === key ? { ...ing, ...patch } : ing)));
  const removeIngredient = (key: number) =>
    setIngredients((prev) => prev.filter((ing) => ing._key !== key));
  const addIngredient = () => {
    const _key = nextKey.current++;
    setIngredients((prev) => [...prev, { _key, name: "", quantity_grams: 0, is_spice: false }]);
  };

  const setStepAt = (key: number, value: string) =>
    setSteps((prev) => prev.map((s) => (s._key === key ? { ...s, value } : s)));
  const removeStep = (key: number) => setSteps((prev) => prev.filter((s) => s._key !== key));
  const addStep = () => {
    const _key = nextKey.current++;
    setSteps((prev) => [...prev, { _key, value: "" }]);
  };

  const nameTrimmed = name.trim();
  const cleanedIngredients: IngredientAmount[] = ingredients
    .map((i) => ({ name: i.name.trim(), quantity_grams: i.quantity_grams, is_spice: i.is_spice }))
    .filter((i) => i.name.length > 0);
  // Backend requires quantity_grams > 0 for every ingredient (spices included).
  // Block the save client-side so the user gets an inline message instead of a
  // 422 from the server.
  const hasBadQuantity = cleanedIngredients.some((i) => !(i.quantity_grams > 0));
  const canSave = nameTrimmed.length > 0 && !hasBadQuantity && !saving;

  const handleSave = () => {
    const cleanedSteps = steps.map((s) => s.value.trim()).filter((s) => s.length > 0);
    const parsed = time.trim() === "" ? null : Number(time);
    const total_time_minutes =
      parsed != null && Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : null;
    onSave({
      ...meal, // preserves meal_type + meal_type_label
      name: nameTrimmed,
      ingredients: cleanedIngredients,
      steps: cleanedSteps,
      total_time_minutes,
    });
  };

  return (
    <div
      style={{
        border: "1px solid #cbd5e1",
        borderRadius: "6px",
        padding: "0.75rem",
        backgroundColor: "#fff",
        marginTop: "0.5rem",
      }}
    >
      <div style={{ fontSize: "0.75rem", color: "#6b7280", marginBottom: "0.4rem" }}>
        Editing {mealTypeLabel(meal.meal_type, meal.meal_type_label)} — meal type is fixed
      </div>

      <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.5rem" }}>
        Name
        <input
          type="text"
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
          style={{ ...inputStyle, marginTop: "0.2rem" }}
          aria-label="Meal name"
        />
      </label>

      <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.5rem" }}>
        Total time (minutes, optional)
        <input
          type="number"
          value={time}
          min={1}
          max={600}
          onChange={(e) => setTime(e.target.value)}
          style={{ ...inputStyle, marginTop: "0.2rem", maxWidth: "10rem" }}
          aria-label="Total time in minutes"
        />
      </label>

      <fieldset style={{ border: "none", padding: 0, margin: "0 0 0.5rem 0" }}>
        <legend style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "0.3rem" }}>
          Ingredients
        </legend>
        {ingredients.map((ing, idx) => (
          <div
            key={ing._key}
            style={{ display: "flex", gap: "0.4rem", alignItems: "center", marginBottom: "0.3rem" }}
          >
            <input
              type="text"
              value={ing.name}
              maxLength={100}
              placeholder="Ingredient"
              onChange={(e) => setIngredientAt(ing._key, { name: e.target.value })}
              style={{ ...inputStyle, flex: 2 }}
              aria-label={`Ingredient ${idx + 1} name`}
            />
            <input
              type="number"
              value={ing.quantity_grams}
              min={0}
              placeholder="g"
              onChange={(e) => setIngredientAt(ing._key, { quantity_grams: Number(e.target.value) })}
              style={{ ...inputStyle, flex: 1, maxWidth: "6rem" }}
              aria-label={`Ingredient ${idx + 1} grams`}
            />
            <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: "0.2rem" }}>
              <input
                type="checkbox"
                checked={ing.is_spice ?? false}
                onChange={(e) => setIngredientAt(ing._key, { is_spice: e.target.checked })}
                aria-label={`Ingredient ${idx + 1} is a spice`}
              />
              spice
            </label>
            <button
              type="button"
              onClick={() => removeIngredient(ing._key)}
              style={{ ...smallBtn, color: "#b91c1c" }}
              aria-label={`Remove ingredient ${idx + 1}`}
            >
              ✕
            </button>
          </div>
        ))}
        <button type="button" onClick={addIngredient} style={smallBtn}>
          + Add ingredient
        </button>
      </fieldset>

      <fieldset style={{ border: "none", padding: 0, margin: "0 0 0.5rem 0" }}>
        <legend style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "0.3rem" }}>
          Steps
        </legend>
        {steps.map((step, idx) => (
          <div
            key={step._key}
            style={{ display: "flex", gap: "0.4rem", alignItems: "flex-start", marginBottom: "0.3rem" }}
          >
            <span style={{ fontSize: "0.85rem", paddingTop: "0.4rem", color: "#6b7280" }}>{idx + 1}.</span>
            <textarea
              value={step.value}
              maxLength={1000}
              rows={2}
              onChange={(e) => setStepAt(step._key, e.target.value)}
              style={{ ...inputStyle, resize: "vertical" }}
              aria-label={`Step ${idx + 1}`}
            />
            <button
              type="button"
              onClick={() => removeStep(step._key)}
              style={{ ...smallBtn, color: "#b91c1c" }}
              aria-label={`Remove step ${idx + 1}`}
            >
              ✕
            </button>
          </div>
        ))}
        <button type="button" onClick={addStep} style={smallBtn}>
          + Add step
        </button>
      </fieldset>

      {hasBadQuantity && (
        <div role="alert" style={{ color: "#b91c1c", fontSize: "0.8rem", marginBottom: "0.4rem" }}>
          Every ingredient needs a positive amount in grams.
        </div>
      )}
      {error && (
        <div role="alert" style={{ color: "#b91c1c", fontSize: "0.8rem", marginBottom: "0.4rem" }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.3rem" }}>
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave}
          style={{
            padding: "0.35rem 1rem",
            backgroundColor: canSave ? "#16a34a" : "#9ca3af",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: canSave ? "pointer" : "not-allowed",
          }}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          style={{
            padding: "0.35rem 1rem",
            backgroundColor: "#6b7280",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: saving ? "not-allowed" : "pointer",
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
