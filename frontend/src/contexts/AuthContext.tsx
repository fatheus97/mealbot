import { createContext, useContext, useState, useEffect, type ReactNode} from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { LoginResponse, AuthState } from "../types";
import {authFetch} from "../api.ts";
import { usePreferencesStore } from "../store/usePreferencesStore";
import { AutoLoginAfterRegisterError } from "./authErrors";

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => window.localStorage.getItem("mealbot_token"));
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
  }, []);

  const setOnboardingCompleted = (value: boolean) => {
    setOnboardingCompletedState(value);
    if (value) {
      window.localStorage.setItem("mealbot_onboarding", "true");
    } else {
      window.localStorage.removeItem("mealbot_onboarding");
    }
  };

  const login = async (newEmail: string, password: string): Promise<LoginResponse> => {
    const formData = new URLSearchParams();
    formData.append("username", newEmail); // OAuth2 spec uses 'username' for email
    formData.append("password", password);

    const resp = await authFetch(`/users/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" }, // NEW: Form content type
      body: formData
    });

    if (!resp.ok) throw new Error(`Login failed: ${resp.status}`);

    const data = (await resp.json()) as LoginResponse;

    setToken(data.access_token);
    setUserId(data.user_id);
    setEmail(data.email);
    setIsDemo(false);
    setOnboardingCompletedState(data.onboarding_completed);

    window.localStorage.setItem("mealbot_token", data.access_token);
    window.localStorage.setItem("mealbot_user_id", String(data.user_id));
    window.localStorage.setItem("mealbot_user_email", data.email);
    window.localStorage.removeItem("mealbot_is_demo");
    if (data.onboarding_completed) {
      window.localStorage.setItem("mealbot_onboarding", "true");
    } else {
      window.localStorage.removeItem("mealbot_onboarding");
    }

    return data;
  };

  const register = async (newEmail: string, password: string): Promise<LoginResponse> => {
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
      return await login(newEmail, password);
    } catch (err) {
      throw new AutoLoginAfterRegisterError(err);
    }
  };

  const loginDemo = async (): Promise<void> => {
    const resp = await authFetch("/demo/session", { method: "POST" });
    if (!resp.ok) throw new Error(`Demo session failed: ${resp.status}`);

    const data = (await resp.json()) as LoginResponse;

    setToken(data.access_token);
    setUserId(data.user_id);
    setEmail(data.email);
    setIsDemo(true);
    setOnboardingCompletedState(data.onboarding_completed);

    window.localStorage.setItem("mealbot_token", data.access_token);
    window.localStorage.setItem("mealbot_user_id", String(data.user_id));
    window.localStorage.setItem("mealbot_user_email", data.email);
    window.localStorage.setItem("mealbot_is_demo", "true");
    window.localStorage.setItem("mealbot_onboarding", "true");
  };

  const logout = () => {
    // Fire-and-forget server-side revocation. If the token is already invalid
    // or the backend is unreachable, we still clear the client state below so
    // the user actually gets logged out. The server call is best-effort; its
    // only job is to bump the user's token_version so previously-issued
    // tokens can't be used from another device/tab.
    void Promise.resolve(authFetch("/users/logout", { method: "POST" })).catch(
      (err) => console.warn("Server-side logout failed:", err),
    );

    setUserId(null);
    setToken(null);
    setEmail("");
    setIsDemo(false);
    setOnboardingCompletedState(false);
    window.localStorage.removeItem("mealbot_token");
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
  };

  useEffect(() => {
    const handleForceLogout = () => logout();
    window.addEventListener("mealbot:logout", handleForceLogout);
    return () => window.removeEventListener("mealbot:logout", handleForceLogout);
    // Subscribe once for the provider's lifetime. logout() closes over stable
    // setters + queryClient, so an empty dep array is safe and intended.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthContext.Provider value={{ userId, token, email, onboardingCompleted, isDemo, demoEnabled, registrationEnabled, login, logout, setOnboardingCompleted, loginDemo, register }}>
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