import { useEffect, useId, useRef } from "react";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  loadingLabel?: string;
  error?: string | null;
  destructive?: boolean;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Delete",
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  loading = false,
  loadingLabel = "Deleting…",
  error = null,
  destructive = true,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  // Focus Cancel by default — safer choice for a destructive prompt.
  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) {
        // Stop other window-level Escape listeners (e.g. CookbookModal,
        // which also closes on Escape) from firing in the same tick. The
        // confirm dialog must consume the Escape so the parent surface
        // stays open.
        e.stopImmediatePropagation();
        onCancel();
      }
    };
    // Capture phase so we beat any bubble-phase listener attached to window
    // by an ancestor modal — bubble vs. capture order isn't well-defined
    // when both register on `window`, so capture is the safer guarantee.
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onCancel, loading]);

  // Minimal focus trap: cycle Tab/Shift+Tab between Cancel and Confirm so
  // keyboard users can't reach the page underneath. The dialog only has two
  // tabbable controls, so this is exhaustive.
  const handleDialogKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const cancelEl = cancelRef.current;
    const confirmEl = confirmRef.current;
    if (!cancelEl || !confirmEl) return;
    const active = document.activeElement;
    if (e.shiftKey) {
      if (active === cancelEl || !active || !(active instanceof HTMLElement) || !e.currentTarget.contains(active)) {
        e.preventDefault();
        confirmEl.focus();
      }
    } else {
      if (active === confirmEl) {
        e.preventDefault();
        cancelEl.focus();
      }
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onKeyDown={handleDialogKeyDown}
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1100,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !loading) onCancel();
      }}
    >
      <div
        style={{
          backgroundColor: "white",
          color: "#111",
          borderRadius: "10px",
          padding: "1.5rem",
          width: "min(92vw, 380px)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.2)",
          border: "1px solid #e0e0e0",
        }}
      >
        <h3 id={titleId} style={{ margin: "0 0 0.5rem 0", fontSize: "1.05rem" }}>
          {title}
        </h3>
        <p style={{ margin: "0 0 1rem 0", color: "#374151", fontSize: "0.92rem" }}>
          {message}
        </p>

        {error && (
          <div role="alert" style={{ color: "#b91c1c", fontSize: "0.85rem", marginBottom: "0.75rem" }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={loading}
            style={{
              padding: "0.4rem 1rem",
              fontSize: "0.9rem",
              backgroundColor: "#e5e7eb",
              color: "#333",
              border: "none",
              borderRadius: "4px",
              cursor: loading ? "default" : "pointer",
              opacity: loading ? 0.6 : 1,
            }}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={loading}
            style={{
              padding: "0.4rem 1rem",
              fontSize: "0.9rem",
              backgroundColor: destructive ? "#dc2626" : "#2563eb",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: loading ? "default" : "pointer",
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? loadingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
