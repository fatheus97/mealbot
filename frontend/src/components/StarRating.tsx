import { useState } from "react";

interface StarRatingProps {
  rating: number | null;
  onRate: (rating: number) => void;
  disabled?: boolean;
}

export function StarRating({ rating, onRate, disabled = false }: StarRatingProps) {
  const [hoverValue, setHoverValue] = useState<number | null>(null);

  const displayValue = hoverValue ?? rating ?? 0;

  return (
    <span
      style={{ display: "inline-flex", gap: "2px", cursor: disabled ? "default" : "pointer" }}
      onMouseLeave={() => { if (!disabled) setHoverValue(null); }}
    >
      {[1, 2, 3, 4, 5].map((star) => (
        <span
          key={star}
          role="button"
          aria-label={`Rate ${star} star${star > 1 ? "s" : ""}`}
          style={{
            color: star <= displayValue ? "#f59e0b" : "#d1d5db",
            fontSize: "1.2rem",
            userSelect: "none",
            transition: "color 0.1s",
          }}
          onMouseEnter={() => { if (!disabled) setHoverValue(star); }}
          onClick={() => { if (!disabled) onRate(star); }}
        >
          &#9733;
        </span>
      ))}
    </span>
  );
}
