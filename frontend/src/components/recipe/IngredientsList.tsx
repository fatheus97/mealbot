import type { IngredientAmount } from "../../types";

interface Props {
  ingredients: IngredientAmount[];
  // When true, render each ingredient on its own line (cookbook spread view).
  // Default is the inline comma-separated form used in plan/cook-now cards.
  block?: boolean;
}

// Shared ingredient renderer. Spices are sorted to the end and italicized;
// quantities are rounded for display (the underlying gram value stays exact).
export function IngredientsList({ ingredients, block = false }: Props) {
  const sorted = [...ingredients].sort(
    (a, b) => (a.is_spice ? 1 : 0) - (b.is_spice ? 1 : 0),
  );

  if (block) {
    return (
      <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
        {sorted.map((ing, i) => (
          <li key={i} style={{ marginBottom: "0.2rem" }}>
            {ing.is_spice ? (
              <span style={{ fontStyle: "italic" }}>{ing.name}</span>
            ) : (
              <span>
                {ing.name} ({Math.round(ing.quantity_grams)}g)
              </span>
            )}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <>
      {sorted.map((ing, i, arr) => (
        <span key={i}>
          {ing.is_spice ? (
            <span style={{ fontStyle: "italic" }}>{ing.name}</span>
          ) : (
            <span>
              {ing.name} ({Math.round(ing.quantity_grams)}g)
            </span>
          )}
          {i < arr.length - 1 ? ", " : ""}
        </span>
      ))}
    </>
  );
}
