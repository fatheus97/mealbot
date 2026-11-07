import { useI18n } from "../i18n";
import { FloatingAlert } from "./FloatingAlert";
import type { AllergenWarning } from "../types";

/**
 * Tells the user their own edit reintroduced an allergen they declared.
 *
 * **Warns, never blocks.** By the time this renders the edit is already saved.
 * Withholding is right for the app's own output — generation fails closed — but
 * an edit is the user's recipe and their declared allergy, so blocking it would
 * be patronising, is trivially routed around, and would push people to keep a
 * "real" copy somewhere the app cannot check at all.
 *
 * `unchecked` (no warnings, in a shared household whose plan lost its diets and
 * allergies) says the edit could not be checked: silence would read as "all
 * clear" (check-in Q12).
 */
export function AllergenEditWarning({
  warnings,
  unchecked = false,
  onDismiss,
}: {
  warnings: AllergenWarning[];
  unchecked?: boolean;
  onDismiss: () => void;
}) {
  const { t } = useI18n();
  if (warnings.length === 0 && !unchecked) return null;

  // De-duplicated: several ingredients can trip the same allergen, and the
  // headline should name each one once.
  const labels = [...new Set(warnings.map((w) => w.label))];

  return (
    <FloatingAlert dismissLabel="Dismiss allergen warning" onDismiss={onDismiss}>
      {warnings.length === 0 ? (
        <div style={{ flex: 1 }}>
          <strong>{t("planner.editUncheckedHeadline")}</strong>
          <div style={{ marginTop: "0.35rem", fontSize: "0.88rem" }}>
            {t("planner.editUncheckedBody")}
          </div>
        </div>
      ) : (
        <div style={{ flex: 1 }}>
          <strong>Heads up — your edit added {labels.join(", ")}.</strong>
          <div style={{ marginTop: "0.35rem", fontSize: "0.88rem" }}>
            You declared {labels.length === 1 ? "this allergen" : "these allergens"} for this
            plan. We saved your change — it's your recipe — but wanted you to know.
          </div>
          <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
            {/* Capped: a pathological edit could trip dozens and push the dismiss
                button off-screen on a phone. */}
            {warnings.slice(0, 4).map((w, i) => (
              <li key={`${w.allergen}-${i}`}>
                {w.source === "step" ? "In a step: " : ""}
                {w.ingredient}
              </li>
            ))}
          </ul>
        </div>
      )}
    </FloatingAlert>
  );
}
