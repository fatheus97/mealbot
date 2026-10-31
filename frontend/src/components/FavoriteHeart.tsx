import { useI18n } from "../i18n";

interface FavoriteHeartProps {
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
 * #f9f9f9, or one of MealCard's pale accent tints — so these are fixed rather
 * than theme-following.
 *
 * This is an icon-only control, so its glyph IS the component and WCAG 1.4.11
 * wants 3:1. The star it replaced first shipped at #d1d5db / #f59e0b (1.41:1
 * and 2.06:1), which is why test/contrast.test.ts pins both states.
 */
export const FAVORITE_SAVED = "#be123c"; // 6.0:1 on #f9fafb
export const FAVORITE_UNSAVED = "#6b7280"; // 4.6:1 on #f9fafb

// The heart, drawn rather than typed: "♥" renders as a colour emoji on some
// platforms, which ignores CSS colour and would lose the filled/outline pair
// that carries the state.
const HEART_PATH =
  "M12 20.5s-7.5-4.6-9.6-9.2C1 8.1 2.9 4.5 6.4 4.5c2.1 0 3.9 1.2 5.6 3.3 1.7-2.1 3.5-3.3 5.6-3.3 3.5 0 5.4 3.6 4 6.8-2.1 4.6-9.6 9.2-9.6 9.2z";

// Cookbook membership toggle. Replaces the ★ star, which read as a rating (the
// reason the legacy 1-5 star rating was dropped in favour of this single bit).
export function FavoriteHeart({
  isFavorite,
  onToggle,
  disabled = false,
  title,
  size = 1.4,
}: FavoriteHeartProps) {
  const { t } = useI18n();
  const label = isFavorite ? t("cookbook.removeLabel") : t("cookbook.addLabel");
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
        lineHeight: 0,
        transition: "color 0.1s",
      }}
    >
      {/*
        FILLED vs OUTLINE, not two colours of the same shape. The two colours
        are close in luminance (1.3:1 against EACH OTHER), so "saved" would
        otherwise be carried by colour alone (WCAG 1.4.1). The fill carries it.
      */}
      <svg
        aria-hidden="true"
        focusable="false"
        viewBox="0 0 24 24"
        width={`${size}rem`}
        height={`${size}rem`}
        fill={isFavorite ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth={2}
        strokeLinejoin="round"
      >
        <path d={HEART_PATH} />
      </svg>
    </button>
  );
}
