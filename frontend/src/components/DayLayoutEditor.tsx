import { useId, useState } from "react";
import { MEAL_TYPES, type MealType } from "../constants/mealTypes";
import { useI18n } from "../i18n";

// Cheap-enough stable ID. crypto.randomUUID is not always available in the
// Node jsdom test environment without polyfills, so fall back to a random
// string. Collisions inside a single layout are astronomically unlikely.
const newId = (): string =>
  (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `slot-${Math.random().toString(36).slice(2)}-${Date.now()}`);

/**
 * Disabled-control text, and the fill the at-max button sits on.
 *
 * WCAG 1.4.3 EXEMPTS inactive controls, so the old #9ca3af (2.43:1) was not a
 * violation — this is a deliberate house standard above the floor, because the
 * ↑/↓ arrows are disabled at the ends of every list and the at-max button
 * carries real information ("8 slots max"). Kept at one grey for both: it still
 * reads clearly dimmer than the active #374151 (4.63:1 vs 9.88:1).
 *
 * Ratios on every surface this editor renders on — its own #fafafa row, the
 * #fcfcfc day card in MealPlanner, and the white Settings modal via
 * PreferencesForm — are asserted in contrast.test.ts.
 */
export const DISABLED_TEXT = "#6b7280";
export const DISABLED_SURFACE = "#f9fafb";

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
  ariaLabel,
}: DayLayoutEditorProps) {
  const { t } = useI18n();
  const labelId = useId();
  const label = ariaLabel ?? t("layout.ariaLabel");

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
  // What the "+ Add slot" button's STYLING keys off — deliberately the same
  // condition as its `disabled` attribute, so the two cannot drift apart.
  const inactive = disabled || atMax;

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
        {label}
      </span>
      {value.length === 0 && (
        <p style={{ margin: 0, fontSize: "0.85rem", color: "#666" }}>
          {t("layout.empty")}
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
              aria-label={t("layout.slot", { n: idx + 1 })}
              value={slot}
              disabled={disabled}
              onChange={(e) => replaceAt(idx, e.target.value as MealType)}
              style={{ flex: 1, padding: "0.3rem", fontSize: "0.95rem" }}
            >
              {MEAL_TYPES.map((mt) => (
                <option key={mt} value={mt}>
                  {t(`mealType.${mt}` as const)}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label={t("layout.moveUp", { n: idx + 1 })}
              onClick={() => moveUp(idx)}
              disabled={disabled || idx === 0}
              style={slotButtonStyle(disabled || idx === 0)}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={t("layout.moveDown", { n: idx + 1 })}
              onClick={() => moveDown(idx)}
              disabled={disabled || idx === value.length - 1}
              style={slotButtonStyle(disabled || idx === value.length - 1)}
            >
              ↓
            </button>
            <button
              type="button"
              aria-label={t("layout.remove", { n: idx + 1 })}
              onClick={() => removeAt(idx)}
              disabled={disabled}
              // The red has to lose to the disabled grey, not override it —
              // spreading slotButtonStyle and then unconditionally re-setting
              // `color` painted a disabled ✕ in full active red.
              style={{ ...slotButtonStyle(disabled), color: disabled ? DISABLED_TEXT : "#b91c1c" }}
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <button
        type="button"
        onClick={addSlot}
        disabled={inactive}
        style={{
          alignSelf: "flex-start",
          padding: "0.35rem 0.8rem",
          fontSize: "0.9rem",
          // Follows the `disabled` ATTRIBUTE above, not just `atMax`. Branching
          // the styling on the narrower condition rendered a full active blue
          // button that could not be clicked while the parent form was saving.
          // The at-max fill is a shade lighter than the obvious #f3f4f6 so the
          // one DISABLED_TEXT grey clears AA here too (4.63:1 rather than 4.39).
          backgroundColor: inactive ? DISABLED_SURFACE : "#eff6ff",
          color: inactive ? DISABLED_TEXT : "#1d4ed8",
          border: `1px solid ${inactive ? "#e5e7eb" : "#bfdbfe"}`,
          borderRadius: "4px",
          cursor: inactive ? "not-allowed" : "pointer",
        }}
      >
        {/* The LABEL still keys off atMax alone — "max 8" is only true at the
            cap, and would be a lie while merely saving. */}
        {atMax ? t("layout.addSlotMax", { max: maxSlots }) : t("layout.addSlot")}
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
    // `background: "none"` exposes the ancestor surface, so this needs an
    // explicit colour or the UA `buttontext` takes over (white under a dark OS
    // theme). See .claude/rules/frontend.md.
    color: inactive ? DISABLED_TEXT : "#374151",
  };
}
