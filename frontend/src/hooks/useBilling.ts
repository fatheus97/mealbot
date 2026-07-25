import { useCallback, useState } from "react";
import { createCheckoutSession, createPortalSession } from "../api";
import type { BillingPlan } from "../types";

/**
 * Billing actions: start a Stripe Checkout or open the Customer Portal. Both
 * redirect the whole tab to Stripe on success (so `pending` is intentionally NOT
 * reset on success — the page is navigating away — only on failure, where the
 * button must become usable again).
 */
export function useBilling() {
  const [checkoutPending, setCheckoutPending] = useState(false);
  const [portalPending, setPortalPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startCheckout = useCallback(async (plan: BillingPlan = "monthly") => {
    setError(null);
    setCheckoutPending(true);
    try {
      const url = await createCheckoutSession(plan);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start checkout.");
      setCheckoutPending(false);
    }
  }, []);

  const openPortal = useCallback(async () => {
    setError(null);
    setPortalPending(true);
    try {
      const url = await createPortalSession();
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open the billing portal.");
      setPortalPending(false);
    }
  }, []);

  // Clear a stale error. The paywall modal is mounted for the whole session
  // (only toggles open), so a prior failed checkout's error would otherwise
  // still be showing the next time the modal reopens — reset() on open avoids it.
  const reset = useCallback(() => setError(null), []);

  return { startCheckout, openPortal, checkoutPending, portalPending, error, reset };
}
