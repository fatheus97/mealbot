import { useEffect } from "react";
import { useAuth } from "../../contexts/AuthContext";

/**
 * Handles the redirect back from Stripe Checkout/Portal. Checkout returns to
 * `/?billing=success`, the Customer Portal to `/?billing=managed` (cancel / card
 * update), and a canceled checkout to `/?billing=cancel`. We strip the marker so
 * a reload can't re-trigger, and on `success`/`managed` re-sync the profile —
 * twice, since the subscription webhook can land a beat after the browser
 * returns. Renders nothing.
 */
export function BillingReturnHandler() {
  const { refreshProfile } = useAuth();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const billing = params.get("billing");
    if (billing !== "success" && billing !== "managed" && billing !== "cancel") return;

    // Remove the marker so a refresh/bookmark doesn't re-run this.
    params.delete("billing");
    const qs = params.toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash,
    );

    // `cancel` = the user backed out of Checkout; nothing changed, just clean up.
    if (billing === "cancel") return;
    // No userId gate: refreshProfile self-guards (it calls /users, which 401s and
    // bails if there's somehow no session), so we can't lose the refresh when the
    // localStorage userId hint is momentarily absent.
    void refreshProfile();
    const t = window.setTimeout(() => {
      void refreshProfile();
    }, 2500);
    return () => window.clearTimeout(t);
  }, [refreshProfile]);

  return null;
}
