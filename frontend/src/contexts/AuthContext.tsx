import { createContext, useContext, useState, type ReactNode } from "react";
import type { AuthResponse } from "../types";

const API_BASE = "http://localhost:8000/api";

interface AuthState {
  userId: number | null;
  email: string;
  login: (email: string) => Promise<AuthResponse>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useState<number | null>(() => {
    const stored = window.localStorage.getItem("mealbot_user_id");
    return stored ? Number(stored) : null;
  });

  const [email, setEmail] = useState<string>(() => {
    return window.localStorage.getItem("mealbot_user_email") || "";
  });

  const login = async (newEmail: string): Promise<AuthResponse> => {
    const resp = await fetch(`${API_BASE}/users/?email=${encodeURIComponent(newEmail)}`, { method: "POST" });
    if (!resp.ok) throw new Error(`Login failed: ${resp.status}`);

    const auth = (await resp.json()) as AuthResponse;
    setUserId(auth.user_id);
    setEmail(newEmail);
    window.localStorage.setItem("mealbot_user_id", String(auth.user_id));
    window.localStorage.setItem("mealbot_user_email", newEmail);
    return auth;
  };

  const logout = () => {
    setUserId(null);
    setEmail("");
    window.localStorage.removeItem("mealbot_user_id");
    window.localStorage.removeItem("mealbot_user_email");
  };

  return (
    <AuthContext.Provider value={{ userId, email, login, logout }}>
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