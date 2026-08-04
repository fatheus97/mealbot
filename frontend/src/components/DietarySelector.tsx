import type { CSSProperties } from "react";
import { InfoHint } from "./InfoHint";

import { ALLERGENS, DIET_TYPES } from "../constants/dietary";
import { useI18n } from "../i18n";
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
  const { t } = useI18n();
  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      <div>
        <div style={sectionLabel}>{t("diet.sectionDiets")}</div>
        <div style={chipRow}>
          {DIET_TYPES.map((d) => (
            <Chip
              key={d}
              label={t(`diet.${d}` as const)}
              selected={dietTypes.includes(d)}
              accent="#2563eb"
              onClick={() => onToggleDiet(d)}
              disabled={disabled}
            />
          ))}
        </div>
      </div>

      <div>
        <div style={sectionLabel}>{t("diet.sectionAllergies")}</div>
        <div style={chipRow}>
          {ALLERGENS.map((a) => {
            const chip = (
              <Chip
                key={a}
                label={t(`allergen.${a}` as const)}
                selected={allergens.includes(a)}
                accent="#b91c1c"
                onClick={() => onToggleAllergen(a)}
                disabled={disabled}
              />
            );
            // Sulphites are the one allergen with NO deterministic screen:
            // whether they must be declared depends on the SO2 left in the
            // finished product, which cannot be computed from a recipe
            // (allergen_screen.py drops them from the screenable set).
            //
            // Deliberately still offered rather than removed — declaring it
            // still instructs the model to avoid wine, vinegar and dried
            // fruit, and dropping the chip would take away the only protection
            // these users get. Transparency, not endorsement: keep it, and say
            // at the point of choice how it differs. An inline hint rather than
            // a conditional line, so selecting it shifts no layout.
            if (a !== "sulphites") return chip;
            return (
              <span
                key={a}
                style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
              >
                {chip}
                <InfoHint
                  label={t("diet.sulphiteHintLabel")}
                  text={t("diet.sulphiteHintText")}
                />
              </span>
            );
          })}
        </div>
        {/* Transparency, never a guarantee — mirrors the backend liability rule
            (docs/dietary-reference.md Part 4). Never say "safe". */}
        <div style={{ fontSize: "0.72rem", opacity: 0.75, marginTop: "0.35rem" }}>
          {t("diet.screeningDisclaimer")}
        </div>
      </div>
    </div>
  );
}
