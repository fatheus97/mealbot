import { useState, useEffect, useMemo, useRef, useLayoutEffect } from "react";
import { useCookbook, useRemoveFromCookbook } from "../hooks/useServerState";
import { IngredientsList } from "./recipe/IngredientsList";
import { RecipeSteps } from "./recipe/RecipeSteps";
import { mealTypeLabel } from "../constants/mealTypes";
import type { CookbookItem } from "../types";

interface Props {
  onClose: () => void;
}

// Two-view modal: index page → per-recipe spread (ingredients left, steps
// right). Mimics opening a real cookbook. Backdrop click closes; ESC closes.
export function CookbookModal({ onClose }: Props) {
  const [view, setView] = useState<"index" | "spread">("index");
  const [selected, setSelected] = useState<CookbookItem | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  // Two-stage spread reveal: while the book "opens" (cover widening),
  // textRevealed is false and inks fade out; once the width transition
  // finishes we flip it to true and the recipe inks fade in like a Harry
  // Potter magic book. The opening transition runs ~300ms; we add a small
  // hold so the user perceives the cover settling before the text appears.
  const [textRevealed, setTextRevealed] = useState(false);

  // 250ms debounce keeps the API quiet while the user types. The hook is
  // gated on the debounced value so each keystroke doesn't invalidate the
  // React Query cache.
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQuery(searchInput.trim()), 250);
    return () => clearTimeout(id);
  }, [searchInput]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (view === "spread") {
          setView("index");
          setSelected(null);
        } else {
          onClose();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, onClose]);

  const { data, isLoading, isError } = useCookbook({
    q: debouncedQuery || undefined,
  });
  const removeMutation = useRemoveFromCookbook();

  const items = data?.items ?? [];

  const handleOpenSpread = (item: CookbookItem) => {
    setSelected(item);
    setView("spread");
    setTextRevealed(false);
  };

  const handleBackToIndex = () => {
    setView("index");
    setSelected(null);
    setTextRevealed(false);
  };

  // Stage 2 of the spread reveal: kick off the text fade slightly BEFORE
  // the cover-width transition fully settles, so the two stages overlap
  // and the whole open feels continuous instead of "open … pause … reveal".
  // Cleared on view change so a back-and-forth doesn't queue stray reveals.
  useEffect(() => {
    if (view !== "spread") return;
    const id = setTimeout(() => setTextRevealed(true), 180);
    return () => clearTimeout(id);
  }, [view, selected]);

  const handleRemove = (item: CookbookItem) => {
    removeMutation.mutate(item.meal_entry_id, {
      onSuccess: () => {
        // If the user removed the recipe currently on the spread, snap back
        // to the index. The list query refetches on its own.
        if (selected?.meal_entry_id === item.meal_entry_id) {
          handleBackToIndex();
        }
      },
    });
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Cookbook"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: "1rem",
      }}
    >
      {/* Outer cover — dark leather. Always rendered at fixed dimensions so
          searching, opening a recipe, or paging never resizes the book. The
          spread view exposes a parchment "page" inset inside this cover so
          the cover edges are visible around the pages, like opening a real
          (or Minecraft) book. */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          // Closed-book index is narrow (single cover); the open-book spread
          // doubles the width so two parchment pages fit side-by-side.
          width:
            view === "index"
              ? "min(95%, 440px)"
              : "min(98%, 880px)",
          height: "min(92vh, 640px)",
          backgroundColor: "#3b2412",
          backgroundImage:
            "linear-gradient(135deg, #4a2d16 0%, #2d1a0a 50%, #4a2d16 100%)",
          borderRadius: "8px",
          padding: view === "index" ? "0" : "16px",
          boxShadow:
            "0 12px 40px rgba(0,0,0,0.5), inset 0 0 0 2px #6b4423, inset 0 0 0 4px #2d1a0a",
          fontFamily: "Georgia, 'Times New Roman', serif",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          color: "#f5e9c8",
          transition: "width 0.3s ease, padding 0.3s ease",
          position: "relative",
        }}
      >
        {view === "index" ? (
          <CookbookIndex
            items={items}
            isLoading={isLoading}
            isError={isError}
            searchInput={searchInput}
            onSearch={setSearchInput}
            onOpen={handleOpenSpread}
            onRemove={handleRemove}
            onClose={onClose}
            removingId={removeMutation.isPending ? removeMutation.variables : null}
          />
        ) : (
          selected && (
            <CookbookSpread
              item={selected}
              onBack={handleBackToIndex}
              onClose={onClose}
              onRemove={() => handleRemove(selected)}
              removing={removeMutation.isPending}
              textRevealed={textRevealed}
            />
          )
        )}
      </div>
    </div>
  );
}


interface IndexProps {
  items: CookbookItem[];
  isLoading: boolean;
  isError: boolean;
  searchInput: string;
  onSearch: (s: string) => void;
  onOpen: (item: CookbookItem) => void;
  onRemove: (item: CookbookItem) => void;
  onClose: () => void;
  removingId: number | null | undefined;
}

function CookbookIndex({
  items,
  isLoading,
  isError,
  searchInput,
  onSearch,
  onOpen,
  onRemove,
  onClose,
  removingId,
}: IndexProps) {
  const grouped = useMemo(() => {
    const map = new Map<string, CookbookItem[]>();
    for (const item of items) {
      const label = mealTypeLabel(item.meal_type, item.meal_type_label);
      const list = map.get(label) ?? [];
      list.push(item);
      map.set(label, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  // The index is rendered ON the closed-book cover: dark leather, light
  // serif text. Click a recipe → cover "opens" to the parchment spread.
  // Inner content area is fixed-height (flex:1 inside a fixed-height shell)
  // so debounced search results don't reflow the book.
  return (
    <>
      {/* Close button is absolute so the title can be perfectly centered
          on the cover regardless of header content width. */}
      <button
        type="button"
        aria-label="Close cookbook"
        onClick={onClose}
        style={{
          position: "absolute",
          top: "0.75rem",
          right: "0.9rem",
          background: "none",
          border: "none",
          fontSize: "1.3rem",
          cursor: "pointer",
          color: "#d4b87c",
          opacity: 0.7,
          zIndex: 1,
        }}
      >
        ✕
      </button>

      <header
        style={{
          padding: "2rem 1.5rem 1rem",
          borderBottom: "1px solid #6b4423",
          textAlign: "center",
        }}
      >
        <h2
          style={{
            margin: 0,
            // Layered title styling: a tall serif display family stack with
            // a gold gradient clip + a subtle dark drop shadow so the
            // letters look embossed into the leather cover.
            fontFamily:
              '"Cinzel", "Cormorant Garamond", "Trajan Pro", Georgia, serif',
            fontSize: "1.85rem",
            fontWeight: 600,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            backgroundImage:
              "linear-gradient(180deg, #f9d77a 0%, #d4a637 50%, #8a5a1f 100%)",
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
            WebkitTextFillColor: "transparent",
            color: "transparent",
            textShadow: "0 2px 4px rgba(0,0,0,0.5)",
            filter: "drop-shadow(0 1px 0 rgba(0,0,0,0.6))",
          }}
        >
          Cookbook
        </h2>
        {/* Decorative gold flourish under the title — two short rules with a
            diamond between, the visual cue you'd expect on an old book cover. */}
        <div
          aria-hidden
          style={{
            marginTop: "0.5rem",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "0.5rem",
            color: "#d4a637",
            fontSize: "0.7rem",
          }}
        >
          <span style={{ flex: "0 0 40px", height: "1px", backgroundColor: "#a87f2a" }} />
          <span>◆</span>
          <span style={{ flex: "0 0 40px", height: "1px", backgroundColor: "#a87f2a" }} />
        </div>
      </header>

      {/* Search bar — narrow, centered, doesn't span the full cover width. */}
      <div
        style={{
          padding: "0.85rem 1.5rem 0.75rem",
          borderBottom: "1px solid #6b4423",
          display: "flex",
          justifyContent: "center",
        }}
      >
        <input
          type="text"
          value={searchInput}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search recipes…"
          style={{
            width: "min(100%, 240px)",
            padding: "0.4rem 0.7rem",
            borderRadius: "4px",
            border: "1px solid #6b4423",
            backgroundColor: "rgba(245,233,200,0.08)",
            color: "#f5e9c8",
            fontFamily: "inherit",
            fontSize: "0.95rem",
            textAlign: "center",
          }}
        />
      </div>

      {/* Scroll lives on the inner list; the outer book frame keeps its
          fixed height so a 0-result search doesn't shrink the cover.
          Native scrollbar hidden (off-design on a leather cover); a
          bottom fade-out cues that there's more content to scroll to. */}
      <style>{`
        .cookbook-scroll-hide::-webkit-scrollbar { display: none; }
      `}</style>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          position: "relative",
        }}
      >
        <div
          className="cookbook-scroll-hide"
          style={{
            overflowY: "auto",
            padding: "1rem 1.75rem 1.75rem",
            height: "100%",
            scrollbarWidth: "none" as const,
            msOverflowStyle: "none" as const,
          }}
        >
        {isLoading && <p style={{ opacity: 0.8 }}>Loading…</p>}
        {isError && (
          <p role="alert" style={{ color: "#fca5a5" }}>
            Failed to load cookbook.
          </p>
        )}
        {!isLoading && !isError && items.length === 0 && (
          <div style={{ textAlign: "center", padding: "2rem 0", color: "#d4b87c" }}>
            <p style={{ fontSize: "1.05rem", marginBottom: "0.25rem" }}>
              {searchInput ? "No recipes match your search." : "Your cookbook is empty."}
            </p>
            {!searchInput && (
              <p style={{ fontSize: "0.9rem", opacity: 0.85 }}>
                Star a recipe in the planner or Cook Now to keep it here.
              </p>
            )}
          </div>
        )}

        {grouped.map(([label, recipes]) => (
          <section key={label} style={{ marginBottom: "1.25rem" }}>
            <h3
              style={{
                fontFamily: "inherit",
                fontSize: "0.8rem",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: "#d4b87c",
                margin: "0 0 0.5rem 0",
                borderBottom: "1px dotted #6b4423",
                paddingBottom: "0.2rem",
              }}
            >
              {label}
            </h3>
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {recipes.map((item) => (
                <li
                  key={item.meal_entry_id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.75rem",
                    padding: "0.4rem 0",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => onOpen(item)}
                    style={{
                      background: "none",
                      border: "none",
                      color: "#f5e9c8",
                      fontFamily: "inherit",
                      fontSize: "1rem",
                      cursor: "pointer",
                      textAlign: "left",
                      flex: 1,
                      padding: 0,
                      textDecoration: "underline",
                      textDecorationColor: "transparent",
                      textUnderlineOffset: "3px",
                      transition: "text-decoration-color 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.textDecorationColor = "#f5e9c8";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.textDecorationColor = "transparent";
                    }}
                  >
                    {item.name}
                    {item.total_time_minutes != null && (
                      <span style={{ color: "#d4b87c", fontSize: "0.85rem", marginLeft: "0.5rem" }}>
                        · {item.total_time_minutes} min
                      </span>
                    )}
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${item.name} from cookbook`}
                    onClick={() => onRemove(item)}
                    disabled={removingId === item.meal_entry_id}
                    title="Remove from cookbook"
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      color: "#d4b87c",
                      fontSize: "0.9rem",
                      opacity: removingId === item.meal_entry_id ? 0.4 : 0.75,
                    }}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        </div>
        {/* Bottom fade-out signals scrollability without showing a scrollbar
            that would clash with the leather cover. Pointer-events:none so
            it doesn't intercept clicks on the last list item. Two-stop
            gradient + extra height so the fade reads clearly against the
            cream-on-leather contrast, not just at the very bottom edge. */}
        <div
          aria-hidden
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            height: "56px",
            pointerEvents: "none",
            background:
              "linear-gradient(180deg, rgba(45,26,10,0) 0%, rgba(45,26,10,0.65) 45%, rgba(45,26,10,1) 100%)",
          }}
        />
      </div>
    </>
  );
}


// Shrink the body font on a scroll container until it fits, before falling
// back to scrolling. The recipe pages have a fixed height (the book frame
// is fixed-size by design), so a long ingredients list or step list would
// otherwise force a scrollbar — which we hide for design reasons. Stepping
// the font down 1px at a time gives us "lower font size when it doesn't
// fit" without ever leaving content invisible.
//
// Floors at 12px so unusually long content still scrolls rather than
// becoming illegible. depKey changes whenever the content changes; we
// re-run the fit pass on each new recipe.
function useFitFontSize(
  containerRef: React.RefObject<HTMLDivElement | null>,
  maxPx: number,
  minPx: number,
  depKey: unknown,
): number {
  const [fontPx, setFontPx] = useState(maxPx);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Start fresh each time content changes — otherwise a previous shrink
    // would persist and we'd never grow back for a shorter recipe.
    let size = maxPx;
    setFontPx(size);

    // Two-pass measurement: applying the new font size mutates layout, so
    // we use rAF to read scrollHeight after the browser paints.
    let raf = 0;
    const step = () => {
      const node = containerRef.current;
      if (!node) return;
      // 1px tolerance — sub-pixel rounding can otherwise spin a useless
      // shrink/grow cycle.
      if (node.scrollHeight - node.clientHeight > 1 && size > minPx) {
        size -= 1;
        node.style.fontSize = `${size}px`;
        raf = requestAnimationFrame(step);
      } else {
        setFontPx(size);
      }
    };
    el.style.fontSize = `${size}px`;
    raf = requestAnimationFrame(step);

    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depKey, maxPx, minPx]);

  return fontPx;
}


interface SpreadProps {
  item: CookbookItem;
  onBack: () => void;
  onClose: () => void;
  onRemove: () => void;
  removing: boolean;
  // Stage 2 of the open animation: false during the cover-widening
  // transition (so all recipe inks are invisible — the page looks blank,
  // like a Harry Potter book before the spell), true after the cover
  // settles (text fades in over ~450ms).
  textRevealed: boolean;
}

// Spread = parchment pages floated inside the dark cover. The 16px padding
// on the parent cover container exposes the cover edge on all sides; the
// inner area is two parchment pages joined by a central bound spine.
//
// No top-spanning bar — each page has its own header (left: title +
// "back to index"; right: actions) so the spine runs uninterrupted from
// top to bottom and the layout reads as a true open book.
function CookbookSpread({ item, onBack, onClose, onRemove, removing, textRevealed }: SpreadProps) {
  // Recipe inks fade in only after the cover is open — controls (back, ✕,
  // remove) sit on the parchment too so they fade with the rest. The
  // transition is intentionally a touch slow so it reads as text appearing
  // on a magic page, not a layout pop.
  const inkStyle = {
    opacity: textRevealed ? 1 : 0,
    transition: "opacity 0.25s ease-out",
  };

  // Per-page auto-fit. Ingredients and steps shrink independently so a
  // long ingredients list doesn't shrink steps along with it. depKey is the
  // recipe id so a new selection re-runs the fit pass.
  const ingredientsRef = useRef<HTMLDivElement | null>(null);
  const stepsRef = useRef<HTMLDivElement | null>(null);
  useFitFontSize(ingredientsRef, 16, 12, item.meal_entry_id);
  useFitFontSize(stepsRef, 16, 12, item.meal_entry_id);
  const pageStyleBase = {
    padding: "1rem 1.4rem 1.25rem",
    display: "flex",
    flexDirection: "column" as const,
    minHeight: 0,
    position: "relative" as const,
  };
  const pageScrollStyle = {
    overflowY: "auto" as const,
    flex: 1,
    minHeight: 0,
    scrollbarWidth: "none" as const,
    msOverflowStyle: "none" as const,
  };
  const pageHeaderStyle = {
    // Reserve the same vertical block on both pages so the recipe name and
    // the STEPS heading sit at the same height across the spine.
    minHeight: "3.4rem",
    marginBottom: "0.6rem",
    display: "flex",
    flexDirection: "column" as const,
  };
  const sectionHeading = {
    fontFamily: "inherit",
    margin: 0,
    fontSize: "1rem",
    color: "#7a5a2e",
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
  };

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: "grid",
        gridTemplateColumns: "1fr 10px 1fr",
        backgroundColor: "#f5e9c8",
        borderRadius: "4px",
        boxShadow: "inset 0 0 0 1px #c8a86b",
        color: "#3b2412",
        overflow: "hidden",
      }}
    >
      {/* Left page */}
      <div
        className="cookbook-scroll-hide"
        style={{
          ...pageStyleBase,
          backgroundImage:
            "radial-gradient(ellipse at top right, #faf0d0 0%, #ecdfb0 100%)",
          boxShadow: "inset -10px 0 14px -10px rgba(59,36,18,0.45)",
        }}
      >
        <div style={{ ...pageHeaderStyle, ...inkStyle }}>
          <button
            type="button"
            onClick={onBack}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "#7a5a2e",
              fontFamily: "inherit",
              fontSize: "0.85rem",
              padding: 0,
              marginBottom: "0.35rem",
              alignSelf: "flex-start",
            }}
          >
            ← Back to index
          </button>
          <h2 style={{ margin: 0, fontFamily: "inherit", fontSize: "1.35rem", color: "#3b2412", lineHeight: 1.15 }}>
            {item.name}
          </h2>
          <div style={{ fontSize: "0.85rem", color: "#7a5a2e", marginTop: "0.15rem" }}>
            {mealTypeLabel(item.meal_type, item.meal_type_label)}
            {item.total_time_minutes != null && ` · ${item.total_time_minutes} min`}
          </div>
        </div>

        <h3 style={{ ...sectionHeading, marginBottom: "0.5rem", ...inkStyle }}>
          Ingredients
        </h3>
        <div
          ref={ingredientsRef}
          className="cookbook-scroll-hide"
          style={{ ...pageScrollStyle, ...inkStyle }}
        >
          <IngredientsList ingredients={item.ingredients} block />
        </div>
      </div>

      {/* Spine — uninterrupted top-to-bottom. */}
      <div
        style={{
          background:
            "linear-gradient(90deg, #a8804a 0%, #6b4423 50%, #a8804a 100%)",
          boxShadow: "inset 0 0 4px rgba(0,0,0,0.5)",
        }}
      />

      {/* Right page */}
      <div
        className="cookbook-scroll-hide"
        style={{
          ...pageStyleBase,
          backgroundImage:
            "radial-gradient(ellipse at top left, #faf0d0 0%, #ecdfb0 100%)",
          boxShadow: "inset 10px 0 14px -10px rgba(59,36,18,0.45)",
        }}
      >
        {/* ✕ close — top-right, on the parchment, fades with the rest. */}
        <button
          type="button"
          aria-label="Close cookbook"
          onClick={onClose}
          style={{
            position: "absolute",
            top: "0.6rem",
            right: "0.8rem",
            background: "none",
            border: "none",
            fontSize: "1.2rem",
            cursor: "pointer",
            color: "#7a5a2e",
            padding: 0,
            ...inkStyle,
          }}
        >
          ✕
        </button>

        {/* STEPS heading aligned with the recipe name on the left page —
            same height as the h2 within the page header block. */}
        <div style={{ ...pageHeaderStyle, justifyContent: "flex-end", ...inkStyle }}>
          <h3 style={{ ...sectionHeading, fontSize: "1.1rem", marginBottom: "0.15rem" }}>
            Steps
          </h3>
        </div>

        <div
          ref={stepsRef}
          className="cookbook-scroll-hide"
          style={{ ...pageScrollStyle, ...inkStyle }}
        >
          <RecipeSteps steps={item.steps} />
        </div>

        {/* Remove pinned to bottom-right, parchment-styled. */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            paddingTop: "0.75rem",
            ...inkStyle,
          }}
        >
          <button
            type="button"
            onClick={onRemove}
            disabled={removing}
            style={{
              background: "none",
              border: "1px solid #c8a86b",
              borderRadius: "4px",
              cursor: removing ? "default" : "pointer",
              color: "#7a5a2e",
              padding: "0.3rem 0.75rem",
              fontFamily: "inherit",
              fontSize: "0.85rem",
              opacity: removing ? 0.5 : 1,
            }}
          >
            {removing ? "Removing…" : "Remove from Cookbook"}
          </button>
        </div>
      </div>
    </div>
  );
}
