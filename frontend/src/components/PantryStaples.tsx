import { useState, useEffect, useRef, type CSSProperties } from "react";
import { useAuth } from "../contexts/AuthContext.tsx";
import { useStaples, useUpdateStaples } from "../hooks/useServerState";

// Keep in step with MAX_STAPLES in app/api/pantry.py — a client-side guard so we
// give a friendly message instead of letting the PUT 422.
const MAX_STAPLES = 200;

// Theme note (see .claude/rules/frontend.md): the panel sets no background, so
// text uses the browser's adaptive default and stays legible in dark AND light.
// Borders are mid-slate (visible on both); the only explicit surface is the
// green Save button, which carries its own contrasting text.
const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.5rem",
  cursor: "pointer",
  userSelect: "none",
};
const mutedStyle: CSSProperties = { fontSize: "0.85rem", color: "#888" };
const chipsWrap: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "0.5rem",
  marginBottom: "0.75rem",
};
const chipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.4rem",
  border: "1px solid #64748b",
  borderRadius: 999,
  padding: "0.2rem 0.35rem 0.2rem 0.7rem",
  fontSize: "0.9rem",
};
const chipRemoveBtn: CSSProperties = {
  border: "none",
  background: "none",
  color: "#ef4444",
  cursor: "pointer",
  fontSize: "1rem",
  lineHeight: 1,
  padding: "0 0.2rem",
};
const inputRow: CSSProperties = { display: "flex", gap: "0.5rem", maxWidth: 420 };
const inputStyle: CSSProperties = {
  flex: 1,
  padding: "0.4rem 0.6rem",
  border: "1px solid #94a3b8",
  borderRadius: 6,
  fontSize: "0.9rem",
};
const addBtn: CSSProperties = {
  padding: "0.4rem 0.9rem",
  border: "1px solid #94a3b8",
  borderRadius: 6,
  background: "transparent",
  cursor: "pointer",
  fontSize: "0.9rem",
};
const saveBtn: CSSProperties = {
  padding: "0.45rem 1rem",
  border: "none",
  borderRadius: 6,
  background: "#16a34a",
  color: "#fff",
  fontSize: "0.9rem",
};

/**
 * The "always have" pantry-staples editor. A staple's name is excluded from the
 * generated shopping list server-side, so salt/oil/flour stop landing on every
 * list. Local edit + explicit Save (mirrors the adjacent Fridge panel); the PUT
 * replaces the whole list, and the server normalizes + dedups.
 */
export function PantryStaples() {
  const { userId } = useAuth();
  const { data: serverStaples, isLoading, error: fetchError } = useStaples(userId);
  const updateStaples = useUpdateStaples();

  const [items, setItems] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const lastServerSig = useRef<string | null>(null);

  // Seed the working list from the server only when the server list actually
  // changes (initial load + after our own save) — never on a no-op refetch, so
  // an in-progress edit isn't clobbered when the window regains focus.
  useEffect(() => {
    if (!serverStaples) return;
    const sig = JSON.stringify(serverStaples.map((s) => s.name));
    if (sig !== lastServerSig.current) {
      lastServerSig.current = sig;
      setItems(serverStaples.map((s) => s.name));
      setDirty(false);
    }
  }, [serverStaples]);

  const addStaple = () => {
    const name = input.trim();
    if (!name) return;
    // Client-side dedup mirrors the server's case-insensitive rule so the chip
    // list doesn't show a duplicate that the save would silently collapse.
    if (items.some((s) => s.toLowerCase() === name.toLowerCase())) {
      setInput("");
      return;
    }
    if (items.length >= MAX_STAPLES) {
      setNotice({ text: `You can have at most ${MAX_STAPLES} staples.`, ok: false });
      return;
    }
    setItems([...items, name]);
    setInput("");
    setDirty(true);
    setNotice(null);
  };

  const removeStaple = (index: number) => {
    setItems(items.filter((_, i) => i !== index));
    setDirty(true);
    setNotice(null);
  };

  const save = () => {
    if (userId === null) return;
    updateStaples.mutate(
      { userId, items: items.map((name) => ({ name })) },
      {
        onSuccess: () => {
          setDirty(false);
          setNotice({ text: "Saved", ok: true });
        },
        onError: (e) =>
          setNotice({ text: e instanceof Error ? e.message : "Save failed", ok: false }),
      },
    );
  };

  const saveDisabled = !dirty || updateStaples.isPending || userId === null;

  return (
    <section style={{ marginBottom: "2rem" }}>
      <div style={headerStyle} onClick={() => setExpanded(!expanded)}>
        <span style={{ fontSize: "0.9rem", color: "#888" }}>
          {expanded ? "▼" : "▶"}
        </span>
        <h2 style={{ margin: 0 }}>Pantry staples</h2>
        {items.length > 0 && <span style={mutedStyle}>({items.length})</span>}
      </div>

      {expanded && (
        <div style={{ marginTop: "1rem" }}>
          <p style={{ ...mutedStyle, margin: "0 0 0.75rem" }}>
            Ingredients you always have on hand (salt, oil, flour…). They're left
            off your generated shopping lists so you don't re-buy them every time.
          </p>

          {isLoading && <p>Loading staples…</p>}
          {fetchError && (
            <p style={{ color: fetchError instanceof TypeError ? "#888" : "red" }}>
              {fetchError instanceof TypeError
                ? "Connecting to server…"
                : `Error: ${fetchError.message}`}
            </p>
          )}

          {items.length > 0 ? (
            <div style={chipsWrap}>
              {items.map((name, i) => (
                <span key={`${name}-${i}`} style={chipStyle}>
                  {name}
                  <button
                    type="button"
                    aria-label={`Remove ${name}`}
                    onClick={() => removeStaple(i)}
                    style={chipRemoveBtn}
                  >
                    {"×"}
                  </button>
                </span>
              ))}
            </div>
          ) : (
            !isLoading && (
              <p style={{ ...mutedStyle, margin: "0 0 0.75rem" }}>
                No staples yet — add the things you never need to buy.
              </p>
            )
          )}

          <div style={inputRow}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addStaple();
                }
              }}
              placeholder="Add a staple (e.g. olive oil)"
              maxLength={100}
              aria-label="New staple name"
              style={inputStyle}
            />
            <button type="button" onClick={addStaple} style={addBtn}>
              Add
            </button>
          </div>

          <div
            style={{
              marginTop: "0.75rem",
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
            }}
          >
            <button
              type="button"
              onClick={save}
              disabled={saveDisabled}
              style={{
                ...saveBtn,
                opacity: saveDisabled ? 0.5 : 1,
                cursor: saveDisabled ? "default" : "pointer",
              }}
            >
              {updateStaples.isPending ? "Saving…" : "Save staples"}
            </button>
            {notice && !notice.ok ? (
              <span style={{ fontSize: "0.85rem", color: "red" }}>{notice.text}</span>
            ) : dirty ? (
              <span style={mutedStyle}>Unsaved changes</span>
            ) : notice && notice.ok ? (
              <span style={{ fontSize: "0.85rem", color: "#16a34a" }}>{notice.text}</span>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
