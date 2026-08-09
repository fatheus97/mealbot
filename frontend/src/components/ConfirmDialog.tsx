import { useEffect, useId, useRef, type ReactNode } from "react";
import { useI18n } from "../i18n";

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
  /**
   * Optional content rendered between the message and the buttons — e.g. the
   * fridge's "ate it / threw it out" choice. Plain composition rather than a
   * prop per use case; anything focusable in here is picked up by the focus
   * trap below, which queries the live DOM rather than assuming two buttons.
   */
  children?: ReactNode;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  loading = false,
  loadingLabel,
  error = null,
  destructive = true,
  children,
}: ConfirmDialogProps) {
  const { t } = useI18n();
  // Resolved at RENDER, not as parameter defaults: a default expression cannot
  // call a hook, and an English literal there is what every caller silently
  // inherited.
  const confirmText = confirmLabel ?? t("confirm.delete");
  const cancelText = cancelLabel ?? t("confirm.cancel");
  const loadingText = loadingLabel ?? t("confirm.deleting");
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

  // Focus trap: cycle Tab/Shift+Tab within the dialog so keyboard users can't
  // reach the page underneath.
  //
  // This QUERIES the live DOM instead of cycling the Cancel/Confirm refs, and
  // that is load-bearing now that `children` exists. The ref-pair version was
  // documented as "exhaustive" because the dialog only ever had two tabbable
  // controls — the moment a caller renders a focusable child, Shift+Tab off
  // that child matched none of its cases and fell through to the browser
  // default, escaping the dialog entirely. A trap that silently stops trapping
  // when the markup grows is worse than no trap, because nothing looks broken.
  const handleDialogKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const tabbable = Array.from(
      e.currentTarget.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
      // A disabled control is not tabbable, and neither is a non-checked radio
      // in a group that has a checked member — but the browser handles the
      // latter's arrow-key roving itself, and treating the group as one stop
      // here would fight it. Filtering on `disabled` alone is enough to keep
      // the first/last ends correct, which is all the cycle needs.
    ).filter((el) => !el.hasAttribute("disabled"));
    if (tabbable.length === 0) return;
    const first = tabbable[0];
    const last = tabbable[tabbable.length - 1];
    const active = document.activeElement;
    const inside = active instanceof HTMLElement && e.currentTarget.contains(active);
    if (e.shiftKey) {
      if (!inside || active === first) {
        e.preventDefault();
        last.focus();
      }
    } else if (!inside || active === last) {
      e.preventDefault();
      first.focus();
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

        {children}

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
            {cancelText}
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
            {loading ? loadingText : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
