import { useAuth } from "../../contexts/AuthContext";
import { useBilling } from "../../hooks/useBilling";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

type Variant = "trialing" | "active" | "past_due" | "subscribe";

// All variants are self-contained light surfaces (explicit background + explicit
// dark text), so they stay legible in BOTH OS colour schemes — inline styles
// can't reach `@media (prefers-color-scheme)` (see .claude/rules/frontend.md).
const SURFACE: Record<Variant, { bg: string; color: string; border: string }> = {
  trialing: { bg: "#eff6ff", color: "#1e3a8a", border: "#bfdbfe" },
  active: { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
  past_due: { bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
  subscribe: { bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
};

export function SubscriptionBanner() {
  const { isDemo, subscriptionStatus, currentPeriodEnd, isSubscribed } = useAuth();
  const { startCheckout, openPortal, checkoutPending, portalPending, error } = useBilling();

  // Demo accounts can't subscribe. A billing-off / admin / bypass user is
  // entitled with status "none" → nothing to show (handled by the variant below).
  if (isDemo) return null;

  let variant: Variant | null = null;
  if (subscriptionStatus === "past_due") variant = "past_due";
  else if (subscriptionStatus === "trialing") variant = "trialing";
  else if (subscriptionStatus === "active") variant = "active";
  else if (!isSubscribed) variant = "subscribe"; // canceled / none / incomplete while billing is ON
  // isSubscribed === true && status "none" → billing off or admin/demo bypass → no banner.

  if (!variant) return null;

  const renews = formatDate(currentPeriodEnd);
  const surface = SURFACE[variant];

  const message =
    variant === "trialing"
      ? `🎉 Free trial${renews ? ` — renews ${renews}` : ""}.`
      : variant === "active"
        ? `✓ Subscribed${renews ? ` · renews ${renews}` : ""}.`
        : variant === "past_due"
          ? "⚠️ Payment failed — update your card to keep access."
          : "Subscribe to keep generating meal plans & recipes.";

  // past_due sends the user to the Portal to fix their card; the rest either
  // subscribe (no customer yet) or manage an existing subscription.
  const isManage = variant === "active" || variant === "trialing" || variant === "past_due";
  const onClick = isManage ? openPortal : startCheckout;
  const pending = isManage ? portalPending : checkoutPending;
  const label = isManage
    ? variant === "past_due"
      ? "Update payment"
      : "Manage"
    : "Subscribe";
  const primary = variant === "subscribe" || variant === "past_due";

  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: "0.5rem",
        margin: "0.75rem 0",
        padding: "0.6rem 0.85rem",
        background: surface.bg,
        color: surface.color,
        border: `1px solid ${surface.border}`,
        borderRadius: 8,
        fontSize: "0.9rem",
      }}
    >
      <span>
        {message}
        {error && (
          <span role="alert" style={{ color: "#b91c1c", marginLeft: 8 }}>
            {error}
          </span>
        )}
      </span>
      <button
        type="button"
        onClick={onClick}
        disabled={pending}
        style={{
          padding: "0.35rem 0.85rem",
          fontSize: "0.85rem",
          borderRadius: 6,
          cursor: pending ? "default" : "pointer",
          border: primary ? "none" : "1px solid currentColor",
          background: primary ? "#2563eb" : "transparent",
          color: primary ? "#fff" : surface.color,
          opacity: pending ? 0.65 : 1,
          whiteSpace: "nowrap",
        }}
      >
        {pending ? "…" : label}
      </button>
    </div>
  );
}
