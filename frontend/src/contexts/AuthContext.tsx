import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { AuthLoginResponse, AuthState } from "../types";
import { authFetch } from "../api.ts";
import { usePreferencesStore } from "../store/usePreferencesStore";
import { AutoLoginAfterRegisterError } from "./authErrors";

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
  const [isDemo, setIsDemo] = useState<boolean>(
    () => window.localStorage.getItem("mealbot_is_demo") === "true"
  );
  // null = /config not yet resolved; boolean = resolved value. Using null
  // as the unresolved sentinel lets the UI avoid a flash of the wrong
  // copy (e.g. rendering the "closed alpha" notice for the 50-200ms
  // round-trip on deployments where registration is actually open).
  const [demoEnabled, setDemoEnabled] = useState<boolean | null>(null);
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean | null>(null);
  const queryClient = useQueryClient();

  const applyProfile = useCallback((profile: AuthLoginResponse, demoFlag: boolean) => {
    setUserId(profile.id);
    setEmail(profile.email);
    setIsDemo(demoFlag);
    setOnboardingCompletedState(profile.onboarding_completed);
    window.localStorage.setItem("mealbot_user_id", String(profile.id));
    window.localStorage.setItem("mealbot_user_email", profile.email);
    if (demoFlag) {
      window.localStorage.setItem("mealbot_is_demo", "true");
    } else {
      window.localStorage.removeItem("mealbot_is_demo");
    }
    if (profile.onboarding_completed) {
      window.localStorage.setItem("mealbot_onboarding", "true");
    } else {
      window.localStorage.removeItem("mealbot_onboarding");
    }
  }, []);

  const clearLocal = useCallback(() => {
    setUserId(null);
    setEmail("");
    setIsDemo(false);
    setOnboardingCompletedState(false);
    window.localStorage.removeItem("mealbot_user_id");
    window.localStorage.removeItem("mealbot_user_email");
    window.localStorage.removeItem("mealbot_onboarding");
    window.localStorage.removeItem("mealbot_is_demo");

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
    // Gate the "Try Demo" and "Register" buttons on backend feature flags so
    // we don't advertise features that would 4xx. Failure → resolve both to
    // false (safer default: hide everything we can't confirm is enabled).
    // Promise.resolve() wrap keeps tests that replace authFetch with
    // vi.fn() (returns undefined) safe.
    Promise.resolve(authFetch("/config"))
      .then((r) => (r?.ok ? r.json() : null))
      .then((data: { demo_mode?: boolean; registration_enabled?: boolean } | null) => {
        setDemoEnabled(Boolean(data?.demo_mode));
        setRegistrationEnabled(Boolean(data?.registration_enabled));
      })
      .catch(() => {
        setDemoEnabled(false);
        setRegistrationEnabled(false);
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
    if (!resp.ok) throw new Error(`Login failed: ${resp.status}`);
    const profile = (await resp.json()) as AuthLoginResponse;
    // Trust the server's is_demo (same call shape as bootstrap above) so all
    // three entry paths — bootstrap, login, loginDemo — use the same source
    // of truth. /auth/login never produces a demo account today, but this
    // keeps future endpoint changes from quietly desyncing the UI flag.
    applyProfile(profile, Boolean(profile.is_demo));
  }, [applyProfile]);

  const register = useCallback(async (newEmail: string, password: string): Promise<void> => {
    // POST /users/register returns 201 with a plain message, not a token, so
    // we auto-login immediately after so the UI lands on an authenticated
    // session without a second user interaction.
    const resp = await authFetch("/users/register", {
      method: "POST",
      body: JSON.stringify({ email: newEmail, password }),
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
    <AuthContext.Provider value={{ userId, email, onboardingCompleted, isDemo, demoEnabled, registrationEnabled, login, logout, setOnboardingCompleted, loginDemo, register }}>
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
