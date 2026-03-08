// frontend/src/api.ts
import type { StockItem, UserProfile } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";

export async function authFetch(endpoint: string, options: RequestInit = {}) {
  // 1. Grab the token we saved during login
  const token = localStorage.getItem("mealbot_token");

  // 2. Set up default headers (skip Content-Type for FormData — browser sets multipart boundary)
  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
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
    window.dispatchEvent(new Event("mealbot:logout"));
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

export async function scanReceipt(file: File): Promise<StockItem[]> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await authFetch("/fridge/scan", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Receipt scan failed: ${res.status} - ${txt}`);
  }
  return res.json();
}

export async function mergeFridgeItems(items: StockItem[]): Promise<StockItem[]> {
  const res = await authFetch("/fridge/merge", {
    method: "POST",
    body: JSON.stringify(items),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Fridge merge failed: ${res.status} - ${txt}`);
  }
  return res.json();
}