// localStorage session "render hints" — the single owner of these key names.
//
// These are NOT the source of truth for auth: the HttpOnly cookie is. They
// exist so a reload can paint the logged-in UI immediately instead of
// flashing logged-out for the duration of the /users round-trip, which
// AuthContext then reconciles against the server.
//
// Extracted into its own React-free module because there are now TWO writers:
// AuthContext (the SPA at /app) and the static marketing landing at / , whose
// login/register/demo modals authenticate and then hand off to /app. Without
// a shared writer the landing would have to duplicate ~10 literal key names,
// and — more importantly — AuthContext's bootstrap only reconciles with the
// server WHEN A HINT IS PRESENT (see its bootstrap effect), so a landing-side
// login that skipped these writes would drop the user on /app looking logged
// out despite holding a perfectly valid cookie.
//
// Deliberately dependency-free (no React, no api.ts) so the landing bundle can
// import it without pulling the SPA in behind it.

/** Shape this module needs. A structural subset of `AuthLoginResponse` so the
 *  landing can pass a raw `/auth/login` payload without importing SPA types. */
export interface SessionProfile {
  id: number;
  email: string;
  onboarding_completed?: boolean;
  is_demo?: boolean;
  is_admin?: boolean;
  subscription_status?: string | null;
  current_period_end?: string | null;
  cancel_at_period_end?: boolean;
  is_subscribed?: boolean;
  is_comped?: boolean;
  email_verified?: boolean;
}

/** Every key this module owns. Exported so `clearSessionHints` and tests can
 *  never drift out of sync with the writer below. */
export const SESSION_HINT_KEYS = [
  "mealbot_user_id",
  "mealbot_user_email",
  "mealbot_onboarding",
  "mealbot_is_demo",
  "mealbot_is_admin",
  "mealbot_subscription_status",
  "mealbot_current_period_end",
  "mealbot_cancel_at_period_end",
  "mealbot_is_subscribed",
  "mealbot_is_comped",
  "mealbot_email_verified",
] as const;

/** Write `value` when truthy, otherwise remove the key — so a stale hint from
 *  a previous session can never survive into a new one. */
function setOrRemove(key: string, value: string | null | undefined): void {
  if (value) {
    window.localStorage.setItem(key, value);
  } else {
    window.localStorage.removeItem(key);
  }
}

/**
 * Persist the render hints for a freshly-authenticated profile.
 *
 * `demoFlag` is passed separately rather than read off the profile because the
 * server's `is_demo` is the authority and callers resolve it explicitly (the
 * localStorage hint can be wiped while the cookie survives, and bootstrapping
 * a demo account as non-demo skews UI gating).
 */
export function storeSessionHints(profile: SessionProfile, demoFlag: boolean): void {
  window.localStorage.setItem("mealbot_user_id", String(profile.id));
  window.localStorage.setItem("mealbot_user_email", profile.email);
  window.localStorage.setItem(
    "mealbot_subscription_status",
    profile.subscription_status ?? "none",
  );
  setOrRemove("mealbot_current_period_end", profile.current_period_end);
  setOrRemove("mealbot_cancel_at_period_end", profile.cancel_at_period_end ? "true" : null);
  setOrRemove("mealbot_is_subscribed", profile.is_subscribed ? "true" : null);
  setOrRemove("mealbot_is_comped", profile.is_comped ? "true" : null);
  setOrRemove("mealbot_is_demo", demoFlag ? "true" : null);
  setOrRemove("mealbot_is_admin", profile.is_admin ? "true" : null);
  setOrRemove("mealbot_onboarding", profile.onboarding_completed ? "true" : null);
  // Stored INVERTED (only the unverified case writes a key) so an absent key
  // means "verified" — matching the optimistic default in AuthContext. Without
  // this hint the confirm-your-email banner mounts into flow one round-trip
  // after first paint and shoves the whole page down for every unverified user
  // on every load (the recurring CLS bug in .claude/rules/frontend.md).
  setOrRemove("mealbot_email_verified", profile.email_verified === false ? "false" : null);
}

/** Drop every hint (logout / account switch). Iterates SESSION_HINT_KEYS so a
 *  key added to the writer above can't be forgotten here. */
export function clearSessionHints(): void {
  for (const key of SESSION_HINT_KEYS) {
    window.localStorage.removeItem(key);
  }
}
