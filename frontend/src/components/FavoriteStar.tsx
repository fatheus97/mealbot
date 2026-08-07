interface FavoriteStarProps {
  isFavorite: boolean;
  onToggle: (next: boolean) => void;
  disabled?: boolean;
  // Tooltip override — defaults adapt to current state.
  title?: string;
  size?: number;
}

/**
 * Colours for the two states. Both call sites (CookNowForm's recipe card,
 * MealCard inside the plan output) sit on a PINNED light surface — #f9fafb and
 * #f9f9f9 — so these are fixed rather than theme-following.
 *
 * The old pair was #d1d5db unsaved / #f59e0b saved: 1.41:1 and 2.06:1. This is
 * an icon-only control, so its glyph IS the component and WCAG 1.4.11 wants
 * 3:1; the unsaved star was effectively invisible on the card.
 */
export const FAVORITE_SAVED = "#b45309"; // 4.81:1 on #f9fafb, 5.02:1 on #fff
export const FAVORITE_UNSAVED = "#6b7280"; // 4.63:1 / 4.83:1

// Single ★ toggle for cookbook membership. Replaces the legacy 1–5 StarRating.
export function FavoriteStar({
  isFavorite,
  onToggle,
  disabled = false,
  title,
  size = 1.4,
}: FavoriteStarProps) {
  const label = isFavorite ? "Remove from cookbook" : "Add to cookbook";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={isFavorite}
      aria-label={label}
      title={title ?? label}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onToggle(!isFavorite);
      }}
      style={{
        background: "none",
        border: "none",
        padding: 0,
        cursor: disabled ? "default" : "pointer",
        color: isFavorite ? FAVORITE_SAVED : FAVORITE_UNSAVED,
        fontSize: `${size}rem`,
        lineHeight: 1,
        userSelect: "none",
        transition: "color 0.1s",
      }}
    >
      {/*
        FILLED vs OUTLINE glyph, not two colours of the same filled star.
        Darkening both colours alone would leave the two states at 1.04:1
        against EACH OTHER — near-identical luminance, differing only in hue —
        so "saved" would be carried by colour alone (WCAG 1.4.1). The shape
        carries it instead, which is what the original "hollow when not
        favorited" comment intended before it was implemented as a pale fill.
      */}
      {isFavorite ? "★" : "☆"}
    </button>
  );
}
