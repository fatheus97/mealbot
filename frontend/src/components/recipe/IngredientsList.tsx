import type { IngredientAmount } from "../../types";
import { formatAmount } from "../../utils/pieces";
import { useShowPieces } from "../../contexts/AuthContext";

interface Props {
  ingredients: IngredientAmount[];
  // When true, render each ingredient on its own line (cookbook spread view).
  // Default is the inline comma-separated form used in plan/cook-now cards.
  block?: boolean;
}

// Shared ingredient renderer. Spices are sorted to the end and italicized;
// quantities are rounded for display (the underlying gram value stays exact).
//
// With the "show pieces" preference on, a countable ingredient reads "2 pcs"
// instead of "120g" — see utils/pieces.ts. The exact grams are always kept in
// the `title`, because the count is derived from a typical piece weight and the
// grams are the real stored quantity.
export function IngredientsList({ ingredients, block = false }: Props) {
  const showPieces = useShowPieces();
  const sorted = [...ingredients].sort(
    (a, b) => (a.is_spice ? 1 : 0) - (b.is_spice ? 1 : 0),
  );

  const amount = (ing: IngredientAmount) =>
    formatAmount(ing.quantity_grams, ing.canonical_name, showPieces);

  if (block) {
    return (
      <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
        {sorted.map((ing, i) => {
          const a = amount(ing);
          return (
            <li key={i} style={{ marginBottom: "0.2rem" }}>
              {ing.is_spice ? (
                <span style={{ fontStyle: "italic" }}>{ing.name}</span>
              ) : (
                <span title={a.isPieces ? a.exactGrams : undefined}>
                  {ing.name} ({a.text})
                </span>
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <>
      {sorted.map((ing, i, arr) => {
        const a = amount(ing);
        return (
          <span key={i}>
            {ing.is_spice ? (
              <span style={{ fontStyle: "italic" }}>{ing.name}</span>
            ) : (
              <span title={a.isPieces ? a.exactGrams : undefined}>
                {ing.name} ({a.text})
              </span>
            )}
            {i < arr.length - 1 ? ", " : ""}
          </span>
        );
      })}
    </>
  );
}
