import type { CSSProperties } from "react";
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
 * `position: fixed` so appearing cannot shove the editor down under the user's
 * cursor (the CLS rule in .claude/rules/frontend.md), and a self-contained
 * opaque surface — background AND colour set together — because inline styles
 * cannot reach `@media (prefers-color-scheme)` and a bare background would go
 * white-on-white in dark mode.
 */
export function AllergenEditWarning({
  warnings,
  onDismiss,
}: {
  warnings: AllergenWarning[];
  onDismiss: () => void;
}) {
  if (warnings.length === 0) return null;

  // De-duplicated: several ingredients can trip the same allergen, and the
  // headline should name each one once.
  const labels = [...new Set(warnings.map((w) => w.label))];

  return (
    <div role="alert" style={wrap}>
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
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss allergen warning"
        style={close}
      >
        &times;
      </button>
    </div>
  );
}

const wrap: CSSProperties = {
  position: "fixed",
  top: "1rem",
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 1400,
  maxWidth: "min(560px, calc(100vw - 2rem))",
  display: "flex",
  alignItems: "flex-start",
  gap: "0.75rem",
  backgroundColor: "#fee2e2",
  color: "#7f1d1d",
  border: "1px solid #fecaca",
  borderRadius: 8,
  padding: "0.8rem 1rem",
  boxShadow: "0 2px 12px rgba(0, 0, 0, 0.25)",
};

const close: CSSProperties = {
  background: "none",
  border: "none",
  color: "inherit",
  fontSize: "1.2rem",
  lineHeight: 1,
  cursor: "pointer",
  padding: "0 0.2rem",
};
