import { useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

interface IngredientChipInputProps {
  values: string[];
  onChange: (next: string[]) => void;
  suggestions: string[];
  placeholder?: string;
  id?: string;
}

const MAX_SUGGESTIONS = 8;

/**
 * Chip input with autocomplete against a fridge ingredient list.
 *
 * Enter or comma commits the current text as a chip (fridge match OR free-form).
 * Backspace on empty input removes the last chip. Clicking a suggestion commits it.
 * Duplicates are silently ignored (case-insensitive).
 */
export function IngredientChipInput({
  values,
  onChange,
  suggestions,
  placeholder,
  id,
}: IngredientChipInputProps) {
  const [draft, setDraft] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const lowerValues = useMemo(
    () => new Set(values.map((v) => v.trim().toLowerCase())),
    [values],
  );

  const filteredSuggestions = useMemo(() => {
    const q = draft.trim().toLowerCase();
    if (!q) return [];
    return suggestions
      .filter((s) => {
        const sl = s.toLowerCase();
        return sl.includes(q) && !lowerValues.has(sl);
      })
      .slice(0, MAX_SUGGESTIONS);
  }, [draft, suggestions, lowerValues]);

  const commitChip = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    if (lowerValues.has(trimmed.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...values, trimmed]);
    setDraft("");
  };

  const removeChip = (index: number) => {
    const next = values.slice();
    next.splice(index, 1);
    onChange(next);
  };

  const showSuggestions = isFocused && filteredSuggestions.length > 0;

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commitChip(showSuggestions ? filteredSuggestions[0] : draft);
    } else if (e.key === "Tab" && showSuggestions) {
      e.preventDefault();
      commitChip(filteredSuggestions[0]);
    } else if (e.key === "Backspace" && draft === "" && values.length > 0) {
      e.preventDefault();
      removeChip(values.length - 1);
    }
  };

  return (
    <div style={{ position: "relative", width: "100%", marginTop: "0.25rem" }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "0.25rem",
          padding: "0.25rem 0.5rem",
          border: "1px solid #ccc",
          borderRadius: "4px",
          minHeight: "2rem",
          backgroundColor: "white",
        }}
        onClick={() => inputRef.current?.focus()}
      >
        {values.map((chip, idx) => (
          <span
            key={`${chip}-${idx}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.25rem",
              padding: "0.15rem 0.5rem",
              backgroundColor: "#dbeafe",
              color: "#1e3a8a",
              borderRadius: "12px",
              fontSize: "0.85rem",
            }}
          >
            {chip}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeChip(idx);
              }}
              aria-label={`Remove ${chip}`}
              style={{
                background: "none",
                border: "none",
                color: "#1e3a8a",
                cursor: "pointer",
                padding: 0,
                fontSize: "0.9rem",
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          id={id}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          // Delay blur so suggestion onMouseDown can fire first.
          onBlur={() => setTimeout(() => setIsFocused(false), 120)}
          placeholder={values.length === 0 ? placeholder : ""}
          style={{
            flex: 1,
            minWidth: "8rem",
            border: "none",
            outline: "none",
            padding: "0.15rem",
            fontSize: "0.9rem",
            backgroundColor: "transparent",
            color: "#111",
          }}
        />
      </div>

      {showSuggestions && (
        <ul
          role="listbox"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 10,
            margin: 0,
            padding: 0,
            listStyle: "none",
            backgroundColor: "white",
            border: "1px solid #ccc",
            borderRadius: "4px",
            maxHeight: "14rem",
            overflowY: "auto",
            boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
          }}
        >
          {filteredSuggestions.map((s) => (
            <li
              key={s}
              role="option"
              aria-selected={false}
              // onMouseDown fires before the input's onBlur, so the click
              // registers before the suggestion list disappears.
              onMouseDown={(e) => {
                e.preventDefault();
                commitChip(s);
              }}
              style={{
                padding: "0.35rem 0.6rem",
                cursor: "pointer",
                fontSize: "0.85rem",
                color: "#111",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLLIElement).style.backgroundColor = "#f1f5f9";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLLIElement).style.backgroundColor = "transparent";
              }}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
