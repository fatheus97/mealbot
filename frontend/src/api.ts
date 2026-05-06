// frontend/src/api.ts
import type {
  CookRecipeRequest,
  FavoriteRecipeRequest,
  MealEntrySummary,
  MealPlanResponse,
  SingleRecipeRequest,
  SingleRecipeResponse,
  StockItem,
  UserProfile,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const CSRF_COOKIE_NAME = "mealbot_csrf";

function readCsrfCookie(): string | null {
  // Non-HttpOnly cookie set by /auth/login + /auth/refresh + /auth/demo.
  // Mirrored back as X-CSRF-Token on mutations (double-submit cookie pattern).
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${CSRF_COOKIE_NAME}=([^;]+)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

// Single-flight refresh so N concurrent 401s share one /auth/refresh call.
// Without this, the very first action after access expiry would issue N
// refreshes in parallel — every one rotates the chain, all but the last
// look like reuse, and the user gets force-logged-out.
let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const resp = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      return resp.ok;
    } catch {
      return false;
    } finally {
      // Reset AFTER the awaiters have resolved so a new burst can start fresh.
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export async function authFetch(
  endpoint: string,
  options: RequestInit = {},
  _retry = false,
): Promise<Response> {
  const isFormData = options.body instanceof FormData;
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(options.headers as Record<string, string>) || {},
  };

  if (!SAFE_METHODS.has(method)) {
    const csrf = readCsrfCookie();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    method,
    credentials: "include",
    headers,
  });

  // Auth endpoints handle their own 401 semantics — recursing into refresh
  // here would either loop (refresh → 401 → refresh) or paper over a real
  // login failure with a refresh attempt.
  if (response.status === 401 && !_retry && !endpoint.startsWith("/auth/")) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return authFetch(endpoint, options, true);
    }
    // Refresh dead — server-side session is gone. Tell the SPA to drop UI state.
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
  data: Partial<Pick<UserProfile, "country" | "language" | "measurement_system" | "variability" | "include_spices" | "track_snacks" | "onboarding_completed" | "default_day_layout">>
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

export async function fetchPlan(planId: number): Promise<MealPlanResponse> {
  const res = await authFetch(`/plan/${planId}`);
  if (!res.ok) {
    throw new Error(`Failed to load plan: ${res.status}`);
  }
  return res.json();
}

export async function generateRecipe(
  payload: SingleRecipeRequest,
): Promise<SingleRecipeResponse> {
  const res = await authFetch("/recipe/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Recipe generation failed: ${res.status} - ${txt}`);
  }
  return res.json();
}

export async function cookRecipe(
  payload: CookRecipeRequest,
): Promise<MealEntrySummary> {
  const res = await authFetch("/recipe/cook", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Recipe cook failed: ${res.status} - ${txt}`);
  }
  return res.json();
}

export async function favoriteRecipe(
  payload: FavoriteRecipeRequest,
): Promise<MealEntrySummary> {
  const res = await authFetch("/recipe/favorite", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Recipe favorite failed: ${res.status} - ${txt}`);
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
