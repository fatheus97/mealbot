import { useEffect, useId, useRef, useState } from "react";
import { useBilling } from "../../hooks/useBilling";
import { useAuth } from "../../contexts/AuthContext";
import type { BillingPlan } from "../../types";

// Marketing copy for the plan toggle. The authoritative amount is shown on Stripe's
// hosted checkout page; these are the sticker figures the pricing was set at (EUR,
// tax-inclusive). Annual = €35.88/yr = €2.99/mo, ~40% off monthly.
const PLAN_OPTIONS: {
  plan: BillingPlan;
  label: string;
  price: string;
  sub: string;
  badge?: string;
}[] = [
  { plan: "monthly", label: "Monthly", price: "€4.99", sub: "per month" },
  { plan: "annual", label: "Annual", price: "€2.99", sub: "per month, billed €35.88/yr", badge: "Save 40%" },
];

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
  const { annualBillingAvailable } = useAuth();
  const [plan, setPlan] = useState<BillingPlan>("monthly");
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const laterRef = useRef<HTMLButtonElement | null>(null);

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
  // While a redirect is pending both buttons are disabled (a disabled control
  // reverts focus to <body>), so pin focus to the dialog container instead.
  useEffect(() => {
    if (!open) return;
    if (checkoutPending) dialogRef.current?.focus();
    else laterRef.current?.focus();
  }, [open, checkoutPending]);

  // Focus trap: wrap Tab / Shift+Tab within the dialog's focusable controls, so focus
  // never lands on the page behind the backdrop. Generalised over *all* enabled
  // controls (the plan toggle adds more than the old two), so it stays correct as the
  // control set changes. While checkout is in flight every control is disabled → no
  // focusables → pin focus to the dialog container.
  const handleDialogKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    if (!focusables || focusables.length === 0) {
      e.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  if (!open) return null;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      onKeyDown={handleDialogKeyDown}
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.45)",
        outline: "none",
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
          10-day free trial — no charge until it ends, cancel anytime.
        </p>

        {annualBillingAvailable && (
          <div role="group" aria-label="Billing plan" style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            {PLAN_OPTIONS.map((opt) => {
              const selected = plan === opt.plan;
              return (
                <button
                  key={opt.plan}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setPlan(opt.plan)}
                  disabled={checkoutPending}
                  style={{
                    flex: 1,
                    textAlign: "left",
                    padding: "0.6rem 0.7rem",
                    borderRadius: 8,
                    border: selected ? "2px solid #2563eb" : "1px solid #d1d5db",
                    background: selected ? "#eff6ff" : "#fff",
                    color: "#1f2937",
                    cursor: checkoutPending ? "default" : "pointer",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.25rem" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>{opt.label}</span>
                    {opt.badge && (
                      <span style={{ fontSize: "0.65rem", fontWeight: 700, color: "#166534", background: "#dcfce7", borderRadius: 999, padding: "0.05rem 0.4rem" }}>
                        {opt.badge}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: 2 }}>{opt.price}</div>
                  <div style={{ fontSize: "0.72rem", color: "#6b7280" }}>{opt.sub}</div>
                </button>
              );
            })}
          </div>
        )}

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
            type="button"
            onClick={() => startCheckout(plan)}
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

        {/* The paywall is where money starts changing hands, and it linked to
            neither legal document. Both open in a new tab so reading them does
            not abandon a checkout mid-flow. Colours are pinned against this
            card's own explicit light surface. */}
        <p
          style={{
            margin: "1rem 0 0",
            fontSize: "0.78rem",
            color: "#6b7280",
            textAlign: "right",
          }}
        >
          By subscribing you agree to our{" "}
          <a href="/terms" target="_blank" rel="noopener noreferrer" style={legalLink}>
            Terms of Service
          </a>{" "}
          and{" "}
          <a href="/privacy" target="_blank" rel="noopener noreferrer" style={legalLink}>
            Privacy Policy
          </a>
          .
        </p>
      </div>
    </div>
  );
}

const legalLink: React.CSSProperties = { color: "#2563eb", textDecoration: "underline" };
