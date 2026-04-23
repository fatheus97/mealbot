import { useId, useState } from "react";
import { MEAL_TYPES, MEAL_TYPE_LABELS, type MealType } from "../constants/mealTypes";

// Cheap-enough stable ID. crypto.randomUUID is not always available in the
// Node jsdom test environment without polyfills, so fall back to a random
// string. Collisions inside a single layout are astronomically unlikely.
const newId = (): string =>
  (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `slot-${Math.random().toString(36).slice(2)}-${Date.now()}`);

interface DayLayoutEditorProps {
  value: MealType[];
  onChange: (next: MealType[]) => void;
  // Cap the number of slots. Default matches the backend _MAX_LAYOUT_SLOTS (8).
  maxSlots?: number;
  // Disable all controls (used when the parent form is saving).
  disabled?: boolean;
  // Aria label for the whole region.
  ariaLabel?: string;
}

// Editable, reorderable list of meal-type slots. No drag-and-drop — using
// real buttons for up/down/remove keeps this mobile-friendly and keyboard-
// accessible without pulling in a DnD library. Each slot is a native <select>
// bound to the centralised MealType taxonomy.
export function DayLayoutEditor({
  value,
  onChange,
  maxSlots = 8,
  disabled = false,
  ariaLabel = "Day layout",
}: DayLayoutEditorProps) {
  const labelId = useId();

  // Stable per-slot ID so React can preserve DOM identity across reorder —
  // without this, focus on ↑ / ↓ buttons is dropped to the body when the user
  // moves a slot. Slot values can repeat (two "snack" entries is valid), so
  // we can't key on the enum value itself.
  const [ids, setIds] = useState<string[]>(() => value.map(newId));
  // "Adjusting state while rendering" pattern
  // (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes):
  // if the parent passes a fresh value array with a different length (e.g.
  // after profile load), resize the id array in the same pass. Calling
  // setIds here is safe — React discards this render and re-runs with the
  // new state. An internal same-length mutation by the helpers below keeps
  // `value` and `ids` aligned without hitting this branch.
  const [syncedLength, setSyncedLength] = useState(value.length);
  if (syncedLength !== value.length) {
    setSyncedLength(value.length);
    setIds((prev) => value.map((_, i) => prev[i] ?? newId()));
  }

  const atMax = value.length >= maxSlots;

  const replaceAt = (idx: number, next: MealType) => {
    const arr = [...value];
    arr[idx] = next;
    onChange(arr);
  };

  const removeAt = (idx: number) => {
    setIds((prev) => prev.filter((_, i) => i !== idx));
    onChange(value.filter((_, i) => i !== idx));
  };

  const moveUp = (idx: number) => {
    if (idx <= 0) return;
    setIds((prev) => {
      const arr = [...prev];
      [arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]];
      return arr;
    });
    const arr = [...value];
    [arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]];
    onChange(arr);
  };

  const moveDown = (idx: number) => {
    if (idx >= value.length - 1) return;
    setIds((prev) => {
      const arr = [...prev];
      [arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]];
      return arr;
    });
    const arr = [...value];
    [arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]];
    onChange(arr);
  };

  const addSlot = () => {
    if (atMax) return;
    setIds((prev) => [...prev, newId()]);
    // Default new slot to main_course — it's the least opinionated choice and
    // what users most often add when extending a layout.
    onChange([...value, "main_course"]);
  };

  return (
    <div aria-labelledby={labelId} style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <span id={labelId} style={{ position: "absolute", left: "-9999px" }}>
        {ariaLabel}
      </span>
      {value.length === 0 && (
        <p style={{ margin: 0, fontSize: "0.85rem", color: "#666" }}>
          No default set — plans will use the "Meals per day" count instead.
        </p>
      )}
      <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
        {value.map((slot, idx) => (
          <li
            key={ids[idx] ?? idx}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.3rem 0.5rem",
              border: "1px solid #e0e0e0",
              borderRadius: "6px",
              backgroundColor: "#fafafa",
            }}
          >
            <span style={{ minWidth: "1.5rem", color: "#666", fontSize: "0.9rem" }}>
              {idx + 1}.
            </span>
            <select
              aria-label={`Slot ${idx + 1}`}
              value={slot}
              disabled={disabled}
              onChange={(e) => replaceAt(idx, e.target.value as MealType)}
              style={{ flex: 1, padding: "0.3rem", fontSize: "0.95rem" }}
            >
              {MEAL_TYPES.map((mt) => (
                <option key={mt} value={mt}>
                  {MEAL_TYPE_LABELS[mt]}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label={`Move slot ${idx + 1} up`}
              onClick={() => moveUp(idx)}
              disabled={disabled || idx === 0}
              style={slotButtonStyle(disabled || idx === 0)}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={`Move slot ${idx + 1} down`}
              onClick={() => moveDown(idx)}
              disabled={disabled || idx === value.length - 1}
              style={slotButtonStyle(disabled || idx === value.length - 1)}
            >
              ↓
            </button>
            <button
              type="button"
              aria-label={`Remove slot ${idx + 1}`}
              onClick={() => removeAt(idx)}
              disabled={disabled}
              style={{ ...slotButtonStyle(disabled), color: "#b91c1c" }}
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <button
        type="button"
        onClick={addSlot}
        disabled={disabled || atMax}
        style={{
          alignSelf: "flex-start",
          padding: "0.35rem 0.8rem",
          fontSize: "0.9rem",
          backgroundColor: atMax ? "#f3f4f6" : "#eff6ff",
          color: atMax ? "#9ca3af" : "#1d4ed8",
          border: `1px solid ${atMax ? "#e5e7eb" : "#bfdbfe"}`,
          borderRadius: "4px",
          cursor: disabled || atMax ? "not-allowed" : "pointer",
        }}
      >
        + Add slot{atMax ? ` (max ${maxSlots})` : ""}
      </button>
    </div>
  );
}

function slotButtonStyle(inactive: boolean): React.CSSProperties {
  return {
    background: "none",
    border: "1px solid #d0d0d0",
    borderRadius: "4px",
    padding: "0.1rem 0.45rem",
    fontSize: "0.9rem",
    cursor: inactive ? "not-allowed" : "pointer",
    color: inactive ? "#9ca3af" : "#374151",
  };
}
