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
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: "#f5e9c8",
          color: "#3b2412",
          borderRadius: "10px",
          width: "min(100%, 880px)",
          maxHeight: "92vh",
          display: "flex",
          flexDirection: "column",
          fontFamily: "Georgia, 'Times New Roman', serif",
          boxShadow: "0 12px 40px rgba(0,0,0,0.4)",
          overflow: "hidden",
          border: "1px solid #c8a86b",
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

  return (
    <>
      <header
        style={{
          padding: "1.25rem 1.5rem 0.75rem",
          borderBottom: "1px solid #d4b87c",
          display: "flex",
          alignItems: "center",
          gap: "1rem",
        }}
      >
        <h2 style={{ margin: 0, flex: 1, fontFamily: "inherit" }}>📖 Cookbook</h2>
        <button
          type="button"
          aria-label="Close cookbook"
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            fontSize: "1.4rem",
            cursor: "pointer",
            color: "#3b2412",
          }}
        >
          ✕
        </button>
      </header>

      <div style={{ padding: "0.75rem 1.5rem", borderBottom: "1px solid #d4b87c" }}>
        <input
          type="text"
          value={searchInput}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search recipes…"
          style={{
            width: "100%",
            padding: "0.5rem 0.75rem",
            borderRadius: "6px",
            border: "1px solid #c8a86b",
            backgroundColor: "#fdf8eb",
            color: "inherit",
            fontFamily: "inherit",
            fontSize: "1rem",
          }}
        />
      </div>

      <div style={{ overflowY: "auto", padding: "1rem 1.5rem", flex: 1 }}>
        {isLoading && <p>Loading…</p>}
        {isError && (
          <p role="alert" style={{ color: "#7f1d1d" }}>
            Failed to load cookbook.
          </p>
        )}
        {!isLoading && !isError && items.length === 0 && (
          <div style={{ textAlign: "center", padding: "2rem 0", color: "#7a5a2e" }}>
            <p style={{ fontSize: "1.05rem", marginBottom: "0.25rem" }}>
              {searchInput ? "No recipes match your search." : "Your cookbook is empty."}
            </p>
            {!searchInput && (
              <p style={{ fontSize: "0.9rem" }}>
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
                fontSize: "0.85rem",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "#7a5a2e",
                margin: "0 0 0.5rem 0",
                borderBottom: "1px dotted #c8a86b",
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
                    padding: "0.5rem 0",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => onOpen(item)}
                    style={{
                      background: "none",
                      border: "none",
                      color: "inherit",
                      fontFamily: "inherit",
                      fontSize: "1rem",
                      cursor: "pointer",
                      textAlign: "left",
                      flex: 1,
                      padding: 0,
                      textDecoration: "underline",
                      textDecorationColor: "transparent",
                      transition: "text-decoration-color 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.textDecorationColor = "#7a5a2e";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.textDecorationColor = "transparent";
                    }}
                  >
                    {item.name}
                    {item.total_time_minutes != null && (
                      <span style={{ color: "#7a5a2e", fontSize: "0.85rem", marginLeft: "0.5rem" }}>
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
                      color: "#7a5a2e",
                      fontSize: "0.9rem",
                      opacity: removingId === item.meal_entry_id ? 0.4 : 1,
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

function CookbookSpread({ item, onBack, onClose, onRemove, removing }: SpreadProps) {
  return (
    <>
      <header
        style={{
          padding: "0.85rem 1.5rem",
          borderBottom: "1px solid #d4b87c",
          display: "flex",
          alignItems: "center",
          gap: "1rem",
        }}
      >
        <button
          type="button"
          onClick={onBack}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "inherit",
            fontFamily: "inherit",
            fontSize: "0.95rem",
          }}
        >
          ← Back to index
        </button>
        <div style={{ flex: 1, textAlign: "center" }}>
          <h2 style={{ margin: 0, fontFamily: "inherit", fontSize: "1.3rem" }}>{item.name}</h2>
          <div style={{ fontSize: "0.85rem", color: "#7a5a2e", marginTop: "0.15rem" }}>
            {mealTypeLabel(item.meal_type, item.meal_type_label)}
            {item.total_time_minutes != null && ` · ${item.total_time_minutes} min`}
          </div>
        </div>
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
            padding: "0.25rem 0.6rem",
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
            fontSize: "1.4rem",
            cursor: "pointer",
            color: "#3b2412",
          }}
        >
          ✕
        </button>
      </header>

      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "1fr 2px 1fr",
          overflow: "hidden",
        }}
      >
        <div style={{ overflowY: "auto", padding: "1.25rem 1.5rem" }}>
          <h3 style={{ fontFamily: "inherit", marginTop: 0, fontSize: "1.05rem" }}>
            Ingredients
          </h3>
          <IngredientsList ingredients={item.ingredients} block />
        </div>
        <div style={{ backgroundColor: "#c8a86b", boxShadow: "inset 0 0 6px rgba(0,0,0,0.25)" }} />
        <div style={{ overflowY: "auto", padding: "1.25rem 1.5rem" }}>
          <h3 style={{ fontFamily: "inherit", marginTop: 0, fontSize: "1.05rem" }}>
            Steps
          </h3>
          <RecipeSteps steps={item.steps} />
        </div>
      </div>
    </>
  );
}
