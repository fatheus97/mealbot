import { useState, useEffect, useMemo } from "react";
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
  };

  const handleBackToIndex = () => {
    setView("index");
    setSelected(null);
  };

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
          fixed height so a 0-result search doesn't shrink the cover. */}
      <div style={{ overflowY: "auto", padding: "1rem 1.75rem", flex: 1, minHeight: 0 }}>
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
    </>
  );
}


interface SpreadProps {
  item: CookbookItem;
  onBack: () => void;
  onClose: () => void;
  onRemove: () => void;
  removing: boolean;
}

// Spread = parchment pages floated inside the dark cover. The 16px padding
// on the parent cover container exposes the cover edge on all sides; the
// inner area is two parchment pages joined by a central bound spine.
//
// No top-spanning bar — each page has its own header (left: title +
// "back to index"; right: actions) so the spine runs uninterrupted from
// top to bottom and the layout reads as a true open book.
function CookbookSpread({ item, onBack, onClose, onRemove, removing }: SpreadProps) {
  const pageStyleBase = {
    overflowY: "auto" as const,
    padding: "1rem 1.4rem 1.25rem",
    display: "flex",
    flexDirection: "column" as const,
    minHeight: 0,
  };
  const pageHeaderStyle = {
    paddingBottom: "0.6rem",
    borderBottom: "1px dotted #c8a86b",
    marginBottom: "0.85rem",
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
        style={{
          ...pageStyleBase,
          backgroundImage:
            "radial-gradient(ellipse at top right, #faf0d0 0%, #ecdfb0 100%)",
          boxShadow: "inset -10px 0 14px -10px rgba(59,36,18,0.45)",
        }}
      >
        <div style={pageHeaderStyle}>
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
              marginBottom: "0.5rem",
            }}
          >
            ← Back to index
          </button>
          <h2 style={{ margin: 0, fontFamily: "inherit", fontSize: "1.35rem", color: "#3b2412" }}>
            {item.name}
          </h2>
          <div style={{ fontSize: "0.85rem", color: "#7a5a2e", marginTop: "0.15rem" }}>
            {mealTypeLabel(item.meal_type, item.meal_type_label)}
            {item.total_time_minutes != null && ` · ${item.total_time_minutes} min`}
          </div>
        </div>

        <h3 style={{ fontFamily: "inherit", marginTop: 0, marginBottom: "0.5rem", fontSize: "1rem", color: "#7a5a2e", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Ingredients
        </h3>
        <IngredientsList ingredients={item.ingredients} block />
      </div>

      {/* Spine — uninterrupted top-to-bottom now that there's no spanning header. */}
      <div
        style={{
          background:
            "linear-gradient(90deg, #a8804a 0%, #6b4423 50%, #a8804a 100%)",
          boxShadow: "inset 0 0 4px rgba(0,0,0,0.5)",
        }}
      />

      {/* Right page */}
      <div
        style={{
          ...pageStyleBase,
          backgroundImage:
            "radial-gradient(ellipse at top left, #faf0d0 0%, #ecdfb0 100%)",
          boxShadow: "inset 10px 0 14px -10px rgba(59,36,18,0.45)",
        }}
      >
        <div
          style={{
            ...pageHeaderStyle,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            gap: "0.5rem",
            // Match the left page header's vertical footprint so the dotted
            // rules align across the spine and the pages look like spreads
            // of the same book.
            minHeight: "calc(0.85rem + 1.35rem * 1.2 + 0.85rem + 0.5rem)",
          }}
        >
          <button
            type="button"
            onClick={onRemove}
            disabled={removing}
            title="Remove from cookbook"
            style={{
              background: "none",
              border: "1px solid #c8a86b",
              borderRadius: "4px",
              cursor: removing ? "default" : "pointer",
              color: "#7a5a2e",
              padding: "0.3rem 0.7rem",
              fontFamily: "inherit",
              fontSize: "0.85rem",
              opacity: removing ? 0.5 : 1,
            }}
          >
            {removing ? "Removing…" : "Remove"}
          </button>
          <button
            type="button"
            aria-label="Close cookbook"
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              fontSize: "1.3rem",
              cursor: "pointer",
              color: "#7a5a2e",
              padding: "0 0.25rem",
            }}
          >
            ✕
          </button>
        </div>

        <h3 style={{ fontFamily: "inherit", marginTop: 0, marginBottom: "0.5rem", fontSize: "1rem", color: "#7a5a2e", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Steps
        </h3>
        <RecipeSteps steps={item.steps} />
      </div>
    </div>
  );
}
