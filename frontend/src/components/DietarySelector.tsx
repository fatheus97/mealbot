import type { CSSProperties } from "react";

import {
  ALLERGEN_LABELS,
  ALLERGENS,
  DIET_TYPE_LABELS,
  DIET_TYPES,
} from "../constants/dietary";
import type { Allergen, DietType } from "../constants/dietary";

// Controlled multi-select for combinable diets + structured allergens (dietary
// differentiator slice 5). Reusable by both the Plan-Ahead form (store-backed
// state) and the Cook-Now form (local state) — it owns no state, only renders.
//
// Theme-safety (see .claude/rules/frontend.md — the recurring white-on-white
// bug): an UNSELECTED chip uses a transparent background + a visible border and
// leaves its text to the page's adaptive default `color: inherit`, so it stays
// legible in both light and dark. A SELECTED chip sets an explicit accent
// background AND an explicit white text colour together. Both states carry a
// 1px border so toggling never shifts layout (no CLS).

interface Props {
  dietTypes: DietType[];
  allergens: Allergen[];
  onToggleDiet: (diet: DietType) => void;
  onToggleAllergen: (allergen: Allergen) => void;
  disabled?: boolean;
}

const sectionLabel: CSSProperties = {
  fontWeight: 600,
  fontSize: "0.85rem",
  marginBottom: "0.35rem",
};

const chipRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "0.4rem",
};

const chipBase: CSSProperties = {
  padding: "0.3rem 0.7rem",
  fontSize: "0.8rem",
  lineHeight: 1.2,
  borderRadius: 999,
  fontFamily: "inherit",
  userSelect: "none",
};

function Chip({
  label,
  selected,
  accent,
  onClick,
  disabled,
}: {
  label: string;
  selected: boolean;
  accent: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  const style: CSSProperties = selected
    ? { ...chipBase, background: accent, color: "#fff", border: `1px solid ${accent}` }
    : { ...chipBase, background: "transparent", color: "inherit", border: "1px solid #cbd5e1" };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
      style={{
        ...style,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
      }}
    >
      {label}
    </button>
  );
}

export function DietarySelector({
  dietTypes,
  allergens,
  onToggleDiet,
  onToggleAllergen,
  disabled,
}: Props) {
  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      <div>
        <div style={sectionLabel}>Diets (combine any)</div>
        <div style={chipRow}>
          {DIET_TYPES.map((d) => (
            <Chip
              key={d}
              label={DIET_TYPE_LABELS[d]}
              selected={dietTypes.includes(d)}
              accent="#2563eb"
              onClick={() => onToggleDiet(d)}
              disabled={disabled}
            />
          ))}
        </div>
      </div>

      <div>
        <div style={sectionLabel}>Allergies to avoid</div>
        <div style={chipRow}>
          {ALLERGENS.map((a) => (
            <Chip
              key={a}
              label={ALLERGEN_LABELS[a]}
              selected={allergens.includes(a)}
              accent="#b91c1c"
              onClick={() => onToggleAllergen(a)}
              disabled={disabled}
            />
          ))}
        </div>
        {/* Transparency, never a guarantee — mirrors the backend liability rule
            (docs/dietary-reference.md Part 4). Never say "safe". */}
        <div style={{ fontSize: "0.72rem", opacity: 0.75, marginTop: "0.35rem" }}>
          Recipes are screened against your selected allergens and their common
          derivatives — this is a helper, not a guarantee. Always check product
          labels yourself.
        </div>
      </div>
    </div>
  );
}
