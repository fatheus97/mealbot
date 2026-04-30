interface FavoriteStarProps {
  isFavorite: boolean;
  onToggle: (next: boolean) => void;
  disabled?: boolean;
  // Tooltip override — defaults adapt to current state.
  title?: string;
  size?: number;
}

// Single ★ toggle for cookbook membership. Replaces the legacy 1–5 StarRating.
// Filled gold (#f59e0b) when favorited, hollow grey (#d1d5db) when not.
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
        color: isFavorite ? "#f59e0b" : "#d1d5db",
        fontSize: `${size}rem`,
        lineHeight: 1,
        userSelect: "none",
        transition: "color 0.1s",
      }}
    >
      &#9733;
    </button>
  );
}
