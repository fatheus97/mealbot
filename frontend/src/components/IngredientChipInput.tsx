import { useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useI18n } from "../i18n";
import { MUTED_PAGE_TEXT } from "../constants/theme";

interface IngredientChipInputProps {
  values: string[];
  onChange: (next: string[]) => void;
  suggestions: string[];
  placeholder?: string;
  id?: string;
  /**
   * Hard cap on chips. The server truncates past its own limit WITHOUT telling
   * anyone, so the count is always shown and commits stop at the cap — the user
   * sees the ceiling instead of losing entries to it.
   */
  maxItems?: number;
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
  maxItems,
}: IngredientChipInputProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const lowerValues = useMemo(
    () => new Set(values.map((v) => v.trim().toLowerCase())),
    [values],
  );

  const isFull = maxItems !== undefined && values.length >= maxItems;

  const filteredSuggestions = useMemo(() => {
    const q = draft.trim().toLowerCase();
    if (!q || isFull) return [];
    return suggestions
      .filter((s) => {
        const sl = s.toLowerCase();
        return sl.includes(q) && !lowerValues.has(sl);
      })
      .slice(0, MAX_SUGGESTIONS);
  }, [draft, suggestions, lowerValues, isFull]);

  const commitChip = (raw: string) => {
    // Split on commas so a pasted "a, b, c" becomes separate chips — and, crucially, so a
    // committed chip can NEVER itself contain a comma. Call sites that serialize the chip
    // list into a comma-joined string (e.g. MealPlanner's persisted "avoid" field) rely on
    // that: a comma inside a chip would be indistinguishable from the separator on the next
    // parse, silently multiplying items. Typing a comma is already intercepted by keydown;
    // this covers the paste path, which lands as one onChange with the commas intact.
    const parts = raw.split(",").map((p) => p.trim()).filter((p) => p.length > 0);
    const seen = new Set(lowerValues);
    const additions: string[] = [];
    for (const part of parts) {
      const key = part.toLowerCase();
      if (seen.has(key)) continue; // skip existing + intra-paste duplicates
      seen.add(key);
      additions.push(part);
    }
    // Stop AT the cap rather than letting the server drop the overflow silently.
    // Pasting "a, b, c" into the last free slot keeps "a" and drops the rest —
    // the counter next to the field is what shows why.
    const room = maxItems === undefined ? additions.length : maxItems - values.length;
    const accepted = additions.slice(0, Math.max(0, room));
    if (accepted.length > 0) onChange([...values, ...accepted]);
    // KEEP the draft only when the CAP is what rejected everything. Clearing
    // then would wipe what the user just typed with no trace — the same
    // silent-loss failure this cap exists to prevent, only moved into the input.
    //
    // Keyed off the cap explicitly rather than off `room`: with no maxItems,
    // `room` is additions.length, which is also 0 when every part was a
    // duplicate — so testing `room` would leave the draft stuck on an UNCAPPED
    // field whenever dedup was the only thing rejecting it. Duplicates still
    // clear (the value is already on screen as a chip), and so does a partial
    // accept — something landed, and the counter explains the rest.
    const blockedByCap =
      maxItems !== undefined && additions.length > 0 && accepted.length === 0;
    if (!blockedByCap) setDraft("");
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
              aria-label={t("chips.remove", { chip })}
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

      {maxItems !== undefined && (
        // ALWAYS rendered once maxItems is set — never `{isFull && …}`. This sits
        // directly above other form controls, so mounting it on demand would push
        // them down mid-interaction (the CLS trap in .claude/rules/frontend.md).
        // No explicit `color`: it sits on the adaptive page background, so it
        // inherits the browser's default text colour and stays legible in BOTH
        // schemes. Do not hardcode one here.
        <div
          aria-live="polite"
          style={{
            // MUTED_PAGE_TEXT is `inherit` + 0.75 opacity, so it dims the
            // adaptive default rather than picking a grey that could invert when
            // the scheme flips. At the limit the message matters, so it goes
            // full-strength instead.
            ...(isFull ? {} : MUTED_PAGE_TEXT),
            marginTop: "0.2rem",
            fontSize: "0.75rem",
            textAlign: "right",
            fontWeight: isFull ? 600 : 400,
          }}
        >
          {isFull
            ? t("chips.limitReached", { max: String(maxItems) })
            : t("chips.count", { count: String(values.length), max: String(maxItems) })}
        </div>
      )}

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
