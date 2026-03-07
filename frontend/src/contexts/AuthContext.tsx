import { createContext, useContext, useState, type ReactNode} from "react";
import type { LoginResponse, AuthState } from "../types";
import {authFetch} from "../api.ts";

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
    setOnboardingCompletedState(data.onboarding_completed);

    window.localStorage.setItem("mealbot_token", data.access_token);
    window.localStorage.setItem("mealbot_user_id", String(data.user_id));
    window.localStorage.setItem("mealbot_user_email", data.email);
    if (data.onboarding_completed) {
      window.localStorage.setItem("mealbot_onboarding", "true");
    } else {
      window.localStorage.removeItem("mealbot_onboarding");
    }

    return data;
  };

  const logout = () => {
    setUserId(null);
    setToken(null);
    setEmail("");
    setOnboardingCompletedState(false);
    window.localStorage.removeItem("mealbot_token");
    window.localStorage.removeItem("mealbot_user_id");
    window.localStorage.removeItem("mealbot_user_email");
    window.localStorage.removeItem("mealbot_onboarding");
  };

  return (
    <AuthContext.Provider value={{ userId, token, email, onboardingCompleted, login, logout, setOnboardingCompleted }}>
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