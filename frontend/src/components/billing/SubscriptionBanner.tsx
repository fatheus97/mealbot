import { useAuth } from "../../contexts/AuthContext";
import { useBilling } from "../../hooks/useBilling";
import { useI18n, type TranslationKey } from "../../i18n";
import { formatDate } from "../../i18n/localeFormat";

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
  const { isDemo, subscriptionStatus, currentPeriodEnd, cancelAtPeriodEnd, isSubscribed, isComped } = useAuth();
  const { startCheckout, openPortal, checkoutPending, portalPending, error } = useBilling();
  const { t, locale } = useI18n();

  // Demo and comped ("friendlist") accounts get their access without a
  // subscription, so subscription billing UI is noise (and can be misleading — a
  // comped user with a stray past_due sub would otherwise see a false "update
  // your card" warning). A billing-off / admin user is entitled with status
  // "none" → nothing to show (handled by the variant below).
  if (isDemo || isComped) return null;

  let variant: Variant | null = null;
  if (subscriptionStatus === "past_due") variant = "past_due";
  else if (subscriptionStatus === "trialing") variant = "trialing";
  else if (subscriptionStatus === "active") variant = "active";
  else if (!isSubscribed) variant = "subscribe"; // canceled / none / incomplete while billing is ON
  // isSubscribed === true && status "none" → billing off or admin/demo bypass → no banner.

  if (!variant) return null;

  const periodDate = formatDate(currentPeriodEnd, locale);

  // When canceled-but-still-active (cancel_at_period_end), the period end is when
  // access ENDS, not when it renews — say so instead of "renews". A subscription
  // can be past_due AND canceled at once (card fails, then the user cancels), in
  // which case "update your card to keep access" is wrong — access ends anyway.
  const canceling =
    cancelAtPeriodEnd &&
    (variant === "trialing" || variant === "active" || variant === "past_due");
  // A "canceled — ends {date}" message shouldn't sit on the positive green/blue
  // surface; use the cautionary amber one so colour matches the copy.
  const surface = canceling ? SURFACE.subscribe : SURFACE[variant];

  // A WHOLE sentence per state, picked here and interpolated once. This used to
  // build the message from a stem plus a shared " — renews {date}" suffix,
  // which is untranslatable: Czech joins the clause with a comma rather than a
  // dash, and "obnovuje se" / "končí" govern the date differently, so no single
  // suffix is correct for both. An absent date is a different key, not an empty
  // suffix, for the same reason.
  let messageKey: TranslationKey;
  if (variant === "subscribe") {
    messageKey = "billing.banner.subscribe";
  } else if (canceling) {
    // A canceled TRIAL says "trial"; a canceled subscription (active or
    // past_due) says "subscription" — past_due + canceling means access ends
    // regardless, so "update your card" would be wrong advice.
    messageKey =
      variant === "trialing"
        ? periodDate
          ? "billing.banner.trialCanceledEnds"
          : "billing.banner.trialCanceled"
        : periodDate
          ? "billing.banner.canceledEnds"
          : "billing.banner.canceled";
  } else if (variant === "past_due") {
    messageKey = "billing.banner.pastDue";
  } else if (variant === "trialing") {
    messageKey = periodDate ? "billing.banner.trialRenews" : "billing.banner.trial";
  } else {
    messageKey = periodDate ? "billing.banner.activeRenews" : "billing.banner.active";
  }
  const message = t(messageKey, { date: periodDate });

  // past_due sends the user to the Portal to fix their card; the rest either
  // subscribe (no customer yet) or manage an existing subscription.
  const isManage = variant === "active" || variant === "trialing" || variant === "past_due";
  // Wrap startCheckout so the click event isn't passed as its `plan` arg. The banner
  // is a secondary (re)subscribe entry point and defaults to monthly; the monthly/
  // annual choice lives in the paywall modal.
  const onClick = isManage ? openPortal : () => startCheckout();
  const pending = isManage ? portalPending : checkoutPending;
  const label = isManage
    ? !canceling && variant === "past_due"
      ? t("billing.banner.updatePayment")
      : t("billing.banner.manage")
    : t("billing.banner.subscribeAction");
  const primary = !canceling && (variant === "subscribe" || variant === "past_due");

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
