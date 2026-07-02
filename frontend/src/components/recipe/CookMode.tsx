import { useState } from "react";
import type { PlannedMeal } from "../../types";
import { mealTypeLabel } from "../../constants/mealTypes";

interface Props {
  meal: PlannedMeal;
  // localStorage key so tick progress survives a mid-cook reload. Pass a stable
  // key per meal, e.g. `cookmode:${planId}:${day}:${meal}`.
  storageKey: string;
  // "Finish": marks the meal cooked (parent decides how). Clears saved progress.
  onDone: () => void;
  // "Close": leaves cook mode WITHOUT finishing — progress stays in storage so
  // reopening resumes where you left off.
  onClose: () => void;
  doneLabel?: string;
  donePending?: boolean;
}

type Progress = { ingredients: number[]; steps: number[] };

function readProgress(key: string): Progress {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const p = JSON.parse(raw) as Partial<Progress>;
      return {
        ingredients: Array.isArray(p.ingredients) ? p.ingredients : [],
        steps: Array.isArray(p.steps) ? p.steps : [],
      };
    }
  } catch {
    // corrupt or unavailable storage — start fresh
  }
  return { ingredients: [], steps: [] };
}

function writeProgress(key: string, p: Progress): void {
  try {
    localStorage.setItem(key, JSON.stringify(p));
  } catch {
    // storage full/disabled — the checklist still works in memory this session
  }
}

const rowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: "0.5rem",
  marginBottom: "0.35rem",
  cursor: "pointer",
};

// Real-time cooking checklist: tick ingredients as you gather them and steps as
// you go. Progress is per-meal and persisted to localStorage so a reload (or a
// phone locking mid-cook) doesn't lose your place. Purely client-side — the
// only server interaction is the parent's onDone (which marks the meal cooked).
export function CookMode({
  meal,
  storageKey,
  onDone,
  onClose,
  doneLabel = "Done cooking",
  donePending = false,
}: Props) {
  const [progress, setProgress] = useState<Progress>(() => readProgress(storageKey));

  const toggle = (kind: "ingredients" | "steps", idx: number) => {
    setProgress((prev) => {
      const set = new Set(prev[kind]);
      if (set.has(idx)) set.delete(idx);
      else set.add(idx);
      const next: Progress = { ...prev, [kind]: [...set] };
      writeProgress(storageKey, next);
      return next;
    });
  };

  const ingredientsChecked = new Set(progress.ingredients);
  const stepsChecked = new Set(progress.steps);
  const doneSteps = meal.steps.reduce((n, _s, i) => n + (stepsChecked.has(i) ? 1 : 0), 0);

  const handleDone = () => {
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // ignore — nothing to clean up
    }
    onDone();
  };

  return (
    <div
      style={{
        border: "1px solid #16a34a",
        borderRadius: "6px",
        padding: "0.75rem",
        backgroundColor: "#f0fdf4",
        marginTop: "0.5rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <strong style={{ fontSize: "0.95rem" }}>
          Cooking: {mealTypeLabel(meal.meal_type, meal.meal_type_label)} — {meal.name}
        </strong>
        <span aria-label={`${doneSteps} of ${meal.steps.length} steps done`} style={{ fontSize: "0.85rem", color: "#15803d", fontWeight: 600 }}>
          {doneSteps}/{meal.steps.length} steps
        </span>
      </div>

      <fieldset style={{ border: "none", padding: 0, margin: "0 0 0.6rem 0" }}>
        <legend style={{ fontSize: "0.8rem", fontWeight: 600, color: "#374151", marginBottom: "0.25rem" }}>
          Ingredients
        </legend>
        {meal.ingredients.map((ing, idx) => {
          const checked = ingredientsChecked.has(idx);
          return (
            <label key={idx} style={rowStyle}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle("ingredients", idx)}
                aria-label={`Ingredient: ${ing.name}`}
              />
              <span style={{ fontSize: "0.9rem", textDecoration: checked ? "line-through" : "none", color: checked ? "#9ca3af" : "#111" }}>
                {ing.is_spice ? ing.name : `${ing.name} (${Math.round(ing.quantity_grams)}g)`}
              </span>
            </label>
          );
        })}
      </fieldset>

      <fieldset style={{ border: "none", padding: 0, margin: "0 0 0.6rem 0" }}>
        <legend style={{ fontSize: "0.8rem", fontWeight: 600, color: "#374151", marginBottom: "0.25rem" }}>
          Steps
        </legend>
        {meal.steps.map((step, idx) => {
          const checked = stepsChecked.has(idx);
          return (
            <label key={idx} style={rowStyle}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle("steps", idx)}
                aria-label={`Step ${idx + 1}`}
              />
              <span style={{ fontSize: "0.9rem", lineHeight: 1.4, textDecoration: checked ? "line-through" : "none", color: checked ? "#9ca3af" : "#111" }}>
                {idx + 1}. {step}
              </span>
            </label>
          );
        })}
      </fieldset>

      <div style={{ display: "flex", gap: "0.5rem" }}>
        <button
          type="button"
          onClick={handleDone}
          disabled={donePending}
          style={{
            padding: "0.35rem 1rem",
            backgroundColor: "#16a34a",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: donePending ? "not-allowed" : "pointer",
          }}
        >
          {donePending ? "Saving…" : doneLabel}
        </button>
        <button
          type="button"
          onClick={onClose}
          style={{
            padding: "0.35rem 1rem",
            backgroundColor: "#fff",
            color: "#374151",
            border: "1px solid #d1d5db",
            borderRadius: "4px",
            cursor: "pointer",
          }}
        >
          Close
        </button>
      </div>
    </div>
  );
}
