import { useEffect, useId, useRef, useState } from "react";
import { useBilling } from "../../hooks/useBilling";

/**
 * Global paywall. Opens whenever a gated (generation) call returns 402 — signaled
 * by the `mealbot:paywall` window event that authFetch dispatches — so no call
 * site has to wire it up. Mounted once at the app root.
 *
 * The card is a self-contained light surface (explicit background + dark text),
 * so it reads correctly in both OS colour schemes (.claude/rules/frontend.md).
 */
export function PaywallModal() {
  const [open, setOpen] = useState(false);
  const { startCheckout, checkoutPending, error, reset } = useBilling();
  const titleId = useId();
  const laterRef = useRef<HTMLButtonElement | null>(null);
  const trialRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    // Clear any stale error from a previous attempt on (re)open — the modal is
    // mounted for the whole session, so useBilling's error would otherwise linger.
    const onPaywall = () => {
      reset();
      setOpen(true);
    };
    window.addEventListener("mealbot:paywall", onPaywall);
    return () => window.removeEventListener("mealbot:paywall", onPaywall);
  }, [reset]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !checkoutPending) {
        e.stopImmediatePropagation();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, checkoutPending]);

  // Move focus into the dialog on open (the non-committal "Maybe later", matching
  // ConfirmDialog's focus-the-safe-choice convention) so keyboard/AT users land
  // inside the modal rather than on the now-obscured trigger behind the backdrop.
  useEffect(() => {
    if (open) laterRef.current?.focus();
  }, [open]);

  // Minimal focus trap: the dialog has exactly two tabbable controls, so cycling
  // Tab / Shift+Tab between them is exhaustive and keeps focus off the page behind.
  const handleDialogKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const later = laterRef.current;
    const trial = trialRef.current;
    if (!later || !trial) return;
    const active = document.activeElement;
    if (e.shiftKey) {
      if (active === later) {
        e.preventDefault();
        trial.focus();
      }
    } else if (active === trial) {
      e.preventDefault();
      later.focus();
    }
  };

  if (!open) return null;

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
        zIndex: 1200,
        padding: "1rem",
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !checkoutPending) setOpen(false);
      }}
    >
      <div
        style={{
          backgroundColor: "#fff",
          color: "#1f2937",
          borderRadius: 12,
          padding: "1.5rem",
          width: "min(92vw, 420px)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
          border: "1px solid #e5e7eb",
        }}
      >
        <h3 id={titleId} style={{ margin: "0 0 0.5rem 0", fontSize: "1.15rem" }}>
          Subscription required
        </h3>
        <p style={{ margin: "0 0 1rem 0", color: "#374151", fontSize: "0.95rem", lineHeight: 1.5 }}>
          Generating meal plans and recipes needs an active subscription. Start a
          14-day free trial — no charge until it ends, cancel anytime.
        </p>

        {error && (
          <div role="alert" style={{ color: "#b91c1c", fontSize: "0.85rem", marginBottom: "0.75rem" }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
          <button
            ref={laterRef}
            type="button"
            onClick={() => setOpen(false)}
            disabled={checkoutPending}
            style={{
              padding: "0.45rem 1rem",
              fontSize: "0.9rem",
              backgroundColor: "#e5e7eb",
              color: "#333",
              border: "none",
              borderRadius: 6,
              cursor: checkoutPending ? "default" : "pointer",
              opacity: checkoutPending ? 0.6 : 1,
            }}
          >
            Maybe later
          </button>
          <button
            ref={trialRef}
            type="button"
            onClick={startCheckout}
            disabled={checkoutPending}
            style={{
              padding: "0.45rem 1rem",
              fontSize: "0.9rem",
              backgroundColor: "#2563eb",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: checkoutPending ? "default" : "pointer",
              opacity: checkoutPending ? 0.7 : 1,
            }}
          >
            {checkoutPending ? "Starting…" : "Start free trial"}
          </button>
        </div>
      </div>
    </div>
  );
}
