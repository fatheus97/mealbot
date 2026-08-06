import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { AuthLoginResponse, AuthState } from "../types";
import { authFetch, redeemInvite, resendVerificationEmail } from "../api.ts";
import { usePreferencesStore } from "../store/usePreferencesStore";
import { AutoLoginAfterRegisterError, LoginFailedError } from "./authErrors";
import { captureAttribution, getStoredAttribution } from "../utils/attribution";
import { clearSessionHints, storeSessionHints } from "../auth/sessionHints";

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  // localStorage entries are a UI render hint to avoid a logged-out flash
  // on reload. The cookie is the real source of truth — the bootstrap
  // effect below reconciles by calling /api/users.
  const [userId, setUserId] = useState<number | null>(() => {
    const stored = window.localStorage.getItem("mealbot_user_id");
    return stored ? Number(stored) : null;
  });
  const [email, setEmail] = useState<string>(() => window.localStorage.getItem("mealbot_user_email") || "");
  const [onboardingCompleted, setOnboardingCompletedState] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_onboarding") === "true"
  );
  // Display preference, mirrored here like the other profile-derived render
  // hints so a leaf renderer can read it without a react-query subscription.
  // Defaults false everywhere, so a component rendered outside the provider (or
  // in a bare unit test) simply shows grams.
  const [showPieces, setShowPieces] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_show_pieces") === "true"
  );
  const [isDemo, setIsDemo] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_is_demo") === "true"
  );
  const [isAdmin, setIsAdmin] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_is_admin") === "true"
  );
  // Billing render hints (same pattern as isAdmin): avoid a wrong-copy flash of
  // the subscription banner on reload. Reconciled by the bootstrap /users call.
  const [subscriptionStatus, setSubscriptionStatus] = useState<string>(
    () => window.localStorage.getItem("mealbot_subscription_status") || "none"
  );
  const [currentPeriodEnd, setCurrentPeriodEnd] = useState<string | null>(
    () => window.localStorage.getItem("mealbot_current_period_end")
  );
  const [cancelAtPeriodEnd, setCancelAtPeriodEnd] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_cancel_at_period_end") === "true"
  );
  const [isSubscribed, setIsSubscribed] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_is_subscribed") === "true"
  );
  const [isComped, setIsComped] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_is_comped") === "true"
  );
  // Seeded from the hint, defaulting TRUE when absent (unlike the flags above,
  // which default false). Two reasons: an optimistic default merely delays the
  // nag by one round-trip whereas a pessimistic one would flash "confirm your
  // email" at every verified user on every load; and seeding from the hint
  // means a returning UNVERIFIED user gets the banner on first paint instead of
  // having it shove the page down a round-trip later (CLS). The hint is only
  // written for the unverified case — see storeSessionHints.
  const [emailVerified, setEmailVerified] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_email_verified") !== "false"
  );
  // null = /config not yet resolved; boolean = resolved value. Using null
  // as the unresolved sentinel lets the UI avoid a flash of the wrong
  // copy (e.g. rendering the "closed alpha" notice for the 50-200ms
  // round-trip on deployments where registration is actually open).
  const [demoEnabled, setDemoEnabled] = useState<boolean | null>(null);
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean | null>(null);
  // Whether the annual plan is offered (from /config). Defaults false so the paywall
  // shows monthly-only until config resolves — never a toggle that 400s on submit.
  const [annualBillingAvailable, setAnnualBillingAvailable] = useState<boolean>(false);
  const queryClient = useQueryClient();

  const applyProfile = useCallback((profile: AuthLoginResponse, demoFlag: boolean) => {
    setUserId(profile.id);
    setEmail(profile.email);
    setIsDemo(demoFlag);
    setIsAdmin(Boolean(profile.is_admin));
    setOnboardingCompletedState(profile.onboarding_completed);
    setShowPieces(Boolean(profile.show_pieces));
    window.localStorage.setItem("mealbot_show_pieces", String(Boolean(profile.show_pieces)));
    // Billing state (defensive ?? / Boolean so a pre-billing cached payload or a
    // test mock without these fields degrades to "not subscribed", not undefined).
    const subStatus = profile.subscription_status ?? "none";
    setSubscriptionStatus(subStatus);
    setCurrentPeriodEnd(profile.current_period_end ?? null);
    setCancelAtPeriodEnd(Boolean(profile.cancel_at_period_end));
    setIsSubscribed(Boolean(profile.is_subscribed));
    setIsComped(Boolean(profile.is_comped));
    // `?? true` so a payload predating this field (or a test mock without it)
    // reads as verified rather than nagging someone who has nothing to do.
    setEmailVerified(profile.email_verified ?? true);
    // The landing page's login/register/demo modals write these same hints
    // before handing off to /app — see auth/sessionHints.ts for why that
    // matters (this provider's bootstrap only reconciles when a hint exists).
    storeSessionHints(profile, demoFlag);
  }, []);

  const clearLocal = useCallback(() => {
    setUserId(null);
    setEmail("");
    setIsDemo(false);
    setIsAdmin(false);
    setOnboardingCompletedState(false);
    setShowPieces(false);
    window.localStorage.removeItem("mealbot_show_pieces");
    setSubscriptionStatus("none");
    setCurrentPeriodEnd(null);
    setCancelAtPeriodEnd(false);
    setIsSubscribed(false);
    setIsComped(false);
    setEmailVerified(true);
    clearSessionHints();

    // Prevent cross-account leakage: drop cached server data and reset
    // the persisted preferences store to defaults. Component-local state
    // (e.g. App's openedPlan) is cleared via the userId-keyed remount in App.tsx.
    queryClient.clear();
    // Reset in-memory state first; clearStorage() last so the persist
    // middleware's reset write doesn't immediately re-populate the entry.
    usePreferencesStore.getState().reset();
    void usePreferencesStore.persist.clearStorage();
  }, [queryClient]);

  useEffect(() => {
    // Capture first-touch acquisition attribution as early as possible, before
    // any navigation drops the landing URL's ?utm_* params. No-op once stored.
    captureAttribution();

    // Gate the "Try Demo" and "Register" buttons on backend feature flags so
    // we don't advertise features that would 4xx. Failure → resolve both to
    // false (safer default: hide everything we can't confirm is enabled).
    // Promise.resolve() wrap keeps tests that replace authFetch with
    // vi.fn() (returns undefined) safe.
    Promise.resolve(authFetch("/config"))
      .then((r) => (r?.ok ? r.json() : null))
      .then(
        (
          data: {
            demo_mode?: boolean;
            registration_enabled?: boolean;
            annual_billing_available?: boolean;
          } | null,
        ) => {
          setDemoEnabled(Boolean(data?.demo_mode));
          setRegistrationEnabled(Boolean(data?.registration_enabled));
          setAnnualBillingAvailable(Boolean(data?.annual_billing_available));
        },
      )
      .catch(() => {
        setDemoEnabled(false);
        setRegistrationEnabled(false);
        setAnnualBillingAvailable(false);
      });

    // Reconcile the localStorage render hint with the server. If we have a
    // userId hint, validate the cookie still holds. authFetch handles 401
    // via refresh; if both fail it dispatches mealbot:logout and the
    // listener below clears UI state.
    if (window.localStorage.getItem("mealbot_user_id")) {
      Promise.resolve(authFetch("/users"))
        .then((r) => (r?.ok ? r.json() : null))
        .then((profile: AuthLoginResponse | null) => {
          // Defensive: only apply a payload that *looks like* a user profile.
          // Guards against a misrouted response (test mocks, future endpoint
          // moves) clobbering state with garbage.
          if (profile && typeof profile.id === "number" && typeof profile.email === "string") {
            // Trust the server's is_demo over the localStorage hint — the
            // hint can be wiped (privacy mode, selective cookie clearing)
            // while the cookie survives, and bootstrapping a demo account
            // as a non-demo skews UI gating.
            applyProfile(profile, Boolean(profile.is_demo));
          }
        })
        .catch(() => {
          // Transient network blip — leave the hint in place rather than
          // bouncing the user to the login screen.
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resendVerification = useCallback(async (): Promise<void> => {
    await resendVerificationEmail();
  }, []);

  const refreshProfile = useCallback(async (): Promise<void> => {
    // Re-sync billing state after a Stripe redirect. The webhook that flips the
    // subscription can land just after the browser returns, so callers may retry.
    // Swallow network blips (same as the bootstrap effect) — callers use
    // `void refreshProfile()`, so a throw would surface as an unhandled rejection.
    try {
      const r = await authFetch("/users");
      if (!r?.ok) return;
      const profile = (await r.json()) as AuthLoginResponse;
      if (profile && typeof profile.id === "number" && typeof profile.email === "string") {
        applyProfile(profile, Boolean(profile.is_demo));
      }
    } catch {
      // Transient failure — leave the current (hinted) state in place.
    }
  }, [applyProfile]);

  const setOnboardingCompleted = (value: boolean) => {
    setOnboardingCompletedState(value);
    if (value) {
      window.localStorage.setItem("mealbot_onboarding", "true");
    } else {
      window.localStorage.removeItem("mealbot_onboarding");
    }
  };

  const login = useCallback(async (newEmail: string, password: string): Promise<void> => {
    const resp = await authFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: newEmail, password }),
    });
    if (!resp.ok) throw new LoginFailedError(resp.status);
    const profile = (await resp.json()) as AuthLoginResponse;
    // Trust the server's is_demo (same call shape as bootstrap above) so all
    // three entry paths — bootstrap, login, loginDemo — use the same source
    // of truth. /auth/login never produces a demo account today, but this
    // keeps future endpoint changes from quietly desyncing the UI flag.
    applyProfile(profile, Boolean(profile.is_demo));
  }, [applyProfile]);

  const register = useCallback(async (
    newEmail: string,
    password: string,
    // The user's actual checkbox state, not a constant — see redeemInvite.
    acceptTerms: boolean,
  ): Promise<void> => {
    // POST /users/register returns 201 with a plain message, not a token, so
    // we auto-login immediately after so the UI lands on an authenticated
    // session without a second user interaction.
    const resp = await authFetch("/users/register", {
      method: "POST",
      // Replay the first-touch attribution captured on landing so the signup is
      // traceable to its campaign. Absent keys are simply omitted (→ NULL).
      body: JSON.stringify({
        email: newEmail,
        password,
        accept_terms: acceptTerms,
        ...getStoredAttribution(),
      }),
    });
    if (!resp.ok) {
      // 403 when registration_enabled flipped server-side between /config
      // and submit; 4xx for duplicate email / weak password (backend
      // rejects per its own rules).
      throw new Error(`Registration failed: ${resp.status}`);
    }
    // Distinguish a login-phase failure from a register-phase failure so
    // the caller can tell the user "your account was created, just sign
    // in" instead of "registration failed" (which would prompt them to
    // try again and hit a 409).
    try {
      await login(newEmail, password);
    } catch (err) {
      throw new AutoLoginAfterRegisterError(err);
    }
  }, [login]);

  const registerViaInvite = useCallback(
    async (
      token: string,
      newEmail: string,
      password: string,
      acceptTerms: boolean,
    ): Promise<void> => {
      // Redeem the invite (201, message-only) then auto-login so the invitee
      // lands in an authenticated session — frictionless beta onboarding, unlike
      // password-reset which deliberately does NOT log in. A login-phase failure
      // is wrapped so the caller can say "account created, just sign in".
      await redeemInvite(token, newEmail, password, acceptTerms);
      try {
        await login(newEmail, password);
      } catch (err) {
        throw new AutoLoginAfterRegisterError(err);
      }
    },
    [login],
  );

  const loginDemo = useCallback(async (): Promise<void> => {
    const resp = await authFetch("/auth/demo", { method: "POST" });
    if (!resp.ok) throw new Error(`Demo session failed: ${resp.status}`);
    const profile = (await resp.json()) as AuthLoginResponse;
    applyProfile(profile, Boolean(profile.is_demo));
  }, [applyProfile]);

  const logout = useCallback(async (): Promise<void> => {
    // Fire-and-forget server-side revocation. If the server is unreachable
    // or returns 401, the local clear below still runs — the user must not
    // get trapped in a "can't log out" UI state.
    try {
      await authFetch("/auth/logout", { method: "POST" });
    } catch (err) {
      console.warn("Server-side logout failed:", err);
    }
    clearLocal();
  }, [clearLocal]);

  useEffect(() => {
    // Force-logout signal from authFetch (refresh dead). We only clear the
    // local UI state — NOT call logout() — because the server cookies are
    // already gone, and recursing into POST /auth/logout would just race
    // another 401 → refresh → dispatch cycle.
    const handleForceLogout = () => clearLocal();
    window.addEventListener("mealbot:logout", handleForceLogout);
    return () => window.removeEventListener("mealbot:logout", handleForceLogout);
  }, [clearLocal]);

  return (
    <AuthContext.Provider value={{ userId, email, onboardingCompleted, showPieces, isDemo, isAdmin, demoEnabled, registrationEnabled, annualBillingAvailable, subscriptionStatus, currentPeriodEnd, cancelAtPeriodEnd, isSubscribed, isComped, emailVerified, resendVerification, login, logout, setOnboardingCompleted, loginDemo, register, registerViaInvite, refreshProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

// Custom hook with strict null-checking
// alternative fix is to move this to useAuth.ts
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
}

/**
 * The "show pieces instead of grams" display preference.
 *
 * Provider-TOLERANT, unlike useAuth: ingredient lists are leaf renderers that
 * appear in isolated unit tests and in surfaces mounted outside AuthProvider.
 * No provider means "preference unknown", which must degrade to grams — always
 * the correct rendering — rather than throwing.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useShowPieces(): boolean {
  return useContext(AuthContext)?.showPieces ?? false;
}
