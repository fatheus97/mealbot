// frontend/src/api.ts
import type { UserProfile } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";

export async function authFetch(endpoint: string, options: RequestInit = {}) {
  // 1. Grab the token we saved during login
  const token = localStorage.getItem("mealbot_token");

  // 2. Set up default headers
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };

  // 3. Attach the token if it exists
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // 4. Make the request
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  // 5. Global error handling for expired tokens
  if (response.status === 401) {
    localStorage.removeItem("mealbot_token");
    localStorage.removeItem("mealbot_user_id");
    localStorage.removeItem("mealbot_user_email");
    window.location.reload();
  }

  return response;
}

export async function fetchUserProfile(): Promise<UserProfile> {
  const res = await authFetch("/users");
  if (!res.ok) throw new Error(`Profile fetch failed: ${res.status}`);
  return res.json();
}

export async function updateUserProfile(
  data: Partial<Pick<UserProfile, "country" | "measurement_system" | "variability" | "include_spices" | "onboarding_completed">>
): Promise<UserProfile> {
  const res = await authFetch("/users", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Profile update failed: ${res.status}`);
  return res.json();
}