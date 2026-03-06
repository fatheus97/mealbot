// frontend/src/api.ts
const API_BASE = "http://localhost:8000/api";

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
    console.warn("Unauthorized! Token might be missing or expired.");
    // Optional: window.location.href = "/login" or trigger a logout
  }

  return response;
}