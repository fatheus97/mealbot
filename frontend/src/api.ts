// frontend/src/api.ts
import type {
  AccessRequestItem,
  AccessRequestListResponse,
  AccessRequestStatus,
  ActivityStatsResponse,
  AdminFeedbackDetail,
  AdminFeedbackListResponse,
  AdminUser,
  AdminUserListResponse,
  AdminUserRoleFilter,
  AdminUserStatusFilter,
  AdminUserUpdate,
  BillingPlan,
  CookRecipeRequest,
  FeedbackCreateRequest,
  FeedbackModerationStatus,
  FeedbackStatusFilter,
  FeedbackSubmitResponse,
  FunnelStatsResponse,
  FavoriteRecipeRequest,
  InviteCreateRequest,
  InviteCreateResponse,
  InviteListItem,
  InviteListResponse,
  MealEditRequest,
  MealEntrySummary,
  MealPlanResponse,
  OverviewStats,
  MealEditResponse,
  RevenueStats,
  ScannedItemsResponse,
  SingleRecipeRequest,
  SingleRecipeResponse,
  StatGranularity,
  StockItem,
  UsageByUserResponse,
  UsageStatsResponse,
  UserProfile,
} from "./types";
import { extractErrorDetail } from "./utils/httpError";
import { DEFAULT_LOCALE, useLocaleStore } from "./store/useLocaleStore";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

// Thrown by the generation calls when the backend gates them with 402 (billing
// on + not entitled). A distinct type so the UI can render the friendly
// "subscription required" copy instead of a raw "…failed: 402" string; the
// paywall modal itself is opened globally via the `mealbot:paywall` event that
// authFetch dispatches, so callers don't have to wire it up.
export class PaywallError extends Error {
  constructor(message = "A subscription is required to use this feature.") {
    super(message);
    this.name = "PaywallError";
  }
}

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
    // The picked UI locale, so server-rendered error sentences match the rest
    // of the screen. Without it the backend falls back to the BROWSER's
    // Accept-Language, which is wrong for exactly the person this feature is
    // for: someone running a Czech UI on an English-language machine. It is
    // sent on every request rather than only the logged-out ones because the
    // server ignores it once a request has a user — User.language wins there.
    "Accept-Language": useLocaleStore.getState().locale ?? DEFAULT_LOCALE,
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

  // 402 = paywall (billing on + caller not entitled). Open the modal globally so
  // any current or future gated call surfaces it without per-call-site wiring.
  // Callers still see the 402 response and throw their own (Paywall)Error.
  if (response.status === 402) {
    window.dispatchEvent(new Event("mealbot:paywall"));
  }

  return response;
}

export async function createCheckoutSession(plan: BillingPlan = "monthly"): Promise<string> {
  const res = await authFetch("/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
  if (!res.ok) {
    throw new Error(await extractErrorDetail(res, "Could not start checkout"));
  }
  const data = (await res.json()) as { url: string };
  return data.url;
}

export async function createPortalSession(): Promise<string> {
  const res = await authFetch("/billing/portal", { method: "POST" });
  if (!res.ok) {
    throw new Error(await extractErrorDetail(res, "Could not open the billing portal"));
  }
  const data = (await res.json()) as { url: string };
  return data.url;
}


// --- Password reset (both endpoints are unauthenticated) ---

export async function requestPasswordReset(email: string): Promise<void> {
  // Resolves on any 2xx. The endpoint returns 204 for unknown *and* demo
  // addresses too, on purpose (no account enumeration), so the caller must
  // show the SAME neutral confirmation regardless — do not branch on "found".
  const res = await authFetch("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  if (res.status === 429) {
    throw new Error("Too many attempts. Please wait a minute and try again.");
  }
  if (!res.ok) {
    // 422 = malformed email (Pydantic EmailStr). Anything else is unexpected.
    if (res.status === 422) {
      throw new Error("Please enter a valid email address.");
    }
    throw new Error(`Could not send the reset email (${res.status}).`);
  }
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const res = await authFetch("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (res.ok) return;
  // 400 carries a friendly `detail` string (invalid / expired / used link);
  // 422 is a Pydantic list detail (weak password) — surface a clear message.
  let detail: string | null = null;
  try {
    const parsed = await res.json();
    if (typeof parsed?.detail === "string") detail = parsed.detail;
  } catch {
    // non-JSON body — fall through to a status-based message
  }
  if (res.status === 429) {
    throw new Error("Too many attempts. Please wait a minute and try again.");
  }
  if (res.status === 422) {
    throw new Error(
      detail ?? "Password must be at least 8 characters with an upper- and lower-case letter and a digit.",
    );
  }
  throw new Error(detail ?? `Could not reset your password (${res.status}).`);
}

export async function fetchUserProfile(): Promise<UserProfile> {
  const res = await authFetch("/users");
  if (!res.ok) throw new Error(`Profile fetch failed: ${res.status}`);
  return res.json();
}

export async function updateUserProfile(
  data: Partial<Pick<UserProfile, "country" | "language" | "measurement_system" | "variability" | "include_spices" | "track_snacks" | "show_pieces" | "need_to_use_enabled" | "onboarding_completed" | "default_day_layout">>
): Promise<UserProfile> {
  const res = await authFetch("/users", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Profile update failed: ${res.status}`);
  return res.json();
}

export async function scanReceipt(file: File): Promise<ScannedItemsResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await authFetch("/fridge/scan", {
    method: "POST",
    body: formData,
  });
  if (res.status === 402) throw new PaywallError();
  if (!res.ok) {
    // Was a raw `${status} - ${body}` dump, which only ever surfaced on 5xx.
    // The email-confirmation gate makes 403 a ROUTINE state here, and its
    // detail ("Please confirm your email address…") is user-facing copy — so
    // use the same extractor the other gated call sites use rather than
    // showing the visitor a JSON blob.
    throw new Error(await extractErrorDetail(res, "Receipt scan failed. Please try again."));
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
  if (res.status === 402) throw new PaywallError();
  if (!res.ok) {
    // Surface the backend `detail` — including the fail-closed allergen message
    // (422) — rather than dumping the raw JSON body into the alert.
    throw new Error(await extractErrorDetail(res, "Recipe generation failed. Please try again."));
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

export async function updateMeal(
  planId: number,
  dayIndex: number,
  mealIndex: number,
  body: MealEditRequest,
): Promise<MealEditResponse> {
  const res = await authFetch(
    `/plan/${planId}/days/${dayIndex}/meals/${mealIndex}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
  if (!res.ok) {
    // Surface the backend's human-readable `detail` (e.g. "steps[0] exceeds
    // 1000 characters", "Cannot edit a finished plan…") rather than dumping raw
    // FastAPI JSON into the UI. Pydantic 422s carry a list detail, not a string,
    // so those fall back to the status message.
    let detail: string | null = null;
    try {
      const parsed = await res.json();
      if (typeof parsed?.detail === "string") detail = parsed.detail;
    } catch {
      // non-JSON body — fall back to the status message
    }
    throw new Error(detail ?? `Meal update failed: ${res.status}`);
  }
  return res.json();
}

// --- Admin stats (require an admin session; the backend gates with 403) ---

function statRange(from?: string, to?: string, granularity?: StatGranularity): string {
  const p = new URLSearchParams();
  if (from) p.set("from", from);
  if (to) p.set("to", to);
  if (granularity) p.set("granularity", granularity);
  const qs = p.toString();
  return qs ? `?${qs}` : "";
}

export async function fetchAdminOverview(): Promise<OverviewStats> {
  const res = await authFetch("/admin/stats/overview");
  if (!res.ok) throw new Error(`Admin overview failed: ${res.status}`);
  return res.json();
}

export async function fetchAdminUsage(
  from?: string,
  to?: string,
  granularity: StatGranularity = "day",
): Promise<UsageStatsResponse> {
  const res = await authFetch(`/admin/stats/usage${statRange(from, to, granularity)}`);
  if (!res.ok) throw new Error(`Admin usage failed: ${res.status}`);
  return res.json();
}

export async function fetchAdminUsageByUser(limit = 20): Promise<UsageByUserResponse> {
  const res = await authFetch(`/admin/stats/usage/by-user?limit=${limit}`);
  if (!res.ok) throw new Error(`Admin usage-by-user failed: ${res.status}`);
  return res.json();
}

export async function fetchAdminActivity(
  from?: string,
  to?: string,
  granularity: StatGranularity = "day",
): Promise<ActivityStatsResponse> {
  const res = await authFetch(`/admin/stats/activity${statRange(from, to, granularity)}`);
  if (!res.ok) throw new Error(`Admin activity failed: ${res.status}`);
  return res.json();
}

export async function fetchAdminRevenue(): Promise<RevenueStats> {
  const res = await authFetch("/admin/stats/revenue");
  if (!res.ok) throw new Error(`Admin revenue failed: ${res.status}`);
  return res.json();
}

export async function fetchAdminFunnel(): Promise<FunnelStatsResponse> {
  const res = await authFetch("/admin/stats/funnel");
  if (!res.ok) throw new Error(`Admin funnel failed: ${res.status}`);
  return res.json();
}

// --- User management (admin; the backend gates all of these with 403) ---

export interface AdminUserQuery {
  q?: string;
  status?: AdminUserStatusFilter;
  role?: AdminUserRoleFilter;
  limit?: number;
  offset?: number;
}

/** Pull the backend's `detail` (a plain string on 400/404/409, or the first
 * Pydantic message on a 422) so admin mutation errors surface a real reason.
 *
 * A thin wrapper, not a second implementation: this used to be a near-copy of
 * `extractErrorDetail` whose only real difference was rendering a 422's field
 * errors, which the shared helper now takes as an opt-in. Kept as a named
 * function purely so the thirteen admin call sites don't each repeat the
 * option — delete it the day admin stops wanting field errors. */
function adminErrorDetail(res: Response, fallback: string): Promise<string> {
  return extractErrorDetail(res, fallback, { fieldErrors: true });
}

export async function fetchAdminUsers(
  query: AdminUserQuery = {},
): Promise<AdminUserListResponse> {
  const p = new URLSearchParams();
  if (query.q) p.set("q", query.q);
  if (query.status && query.status !== "all") p.set("status", query.status);
  if (query.role && query.role !== "all") p.set("role", query.role);
  if (query.limit != null) p.set("limit", String(query.limit));
  if (query.offset != null) p.set("offset", String(query.offset));
  const qs = p.toString();
  const res = await authFetch(`/admin/users${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Admin users failed: ${res.status}`);
  return res.json();
}

export async function createAdminUser(body: {
  email: string;
  password: string;
  is_admin?: boolean;
  is_comped?: boolean;
}): Promise<AdminUser> {
  const res = await authFetch("/admin/users", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not create the user"));
  return res.json();
}

export async function updateAdminUser(
  id: number,
  body: AdminUserUpdate,
): Promise<AdminUser> {
  const res = await authFetch(`/admin/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not update the user"));
  return res.json();
}

export async function resetAdminUserOnboarding(id: number): Promise<AdminUser> {
  const res = await authFetch(`/admin/users/${id}/reset-onboarding`, { method: "POST" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not reset onboarding"));
  return res.json();
}

/** Force-confirm a stuck user's address (POST /admin/users/{id}/verify-email).
 *  Server-audited — it bypasses the email-confirmation gate. */
export async function verifyAdminUserEmail(id: number): Promise<AdminUser> {
  const res = await authFetch(`/admin/users/${id}/verify-email`, { method: "POST" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not verify the email"));
  return res.json();
}

export async function forceLogoutAdminUser(id: number): Promise<void> {
  const res = await authFetch(`/admin/users/${id}/logout`, { method: "POST" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not log the user out"));
}

export async function deleteAdminUser(id: number): Promise<void> {
  const res = await authFetch(`/admin/users/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not delete the user"));
}

// --- Admin: invite links ---

export async function createInvite(
  body: InviteCreateRequest = {},
): Promise<InviteCreateResponse> {
  const res = await authFetch("/admin/invites", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not generate the invite"));
  return res.json();
}

export async function fetchInvites(): Promise<InviteListResponse> {
  const res = await authFetch("/admin/invites");
  if (!res.ok) throw new Error(`Admin invites failed: ${res.status}`);
  return res.json();
}

export async function revokeInvite(id: number): Promise<InviteListItem> {
  const res = await authFetch(`/admin/invites/${id}/revoke`, { method: "POST" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not revoke the invite"));
  return res.json();
}

// --- Email confirmation ---

/**
 * Redeem a confirmation link. Unauthenticated on purpose — the token IS the
 * proof, and these links are routinely opened from a phone mail client rather
 * than the browser that registered. Throws on an invalid/expired/used token so
 * the caller can offer a resend.
 */
export async function verifyEmail(token: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/verify-email`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!res.ok) {
    throw new Error("This confirmation link is invalid or has expired.");
  }
}

/** Re-send the confirmation link to the CURRENT user's own address. */
export async function resendVerificationEmail(): Promise<void> {
  const res = await authFetch("/auth/resend-verification", { method: "POST" });
  if (!res.ok) throw new Error("Could not resend the confirmation email.");
}

/**
 * Move the account to a different address.
 *
 * The server re-verifies the password, revokes every OTHER session and rotates
 * this device's cookies on the 204 — so the caller must refresh the profile
 * afterwards: `email` changed and `email_verified` is now false again.
 *
 * Errors are surfaced verbatim through extractErrorDetail because every one of
 * them is something the user must act on differently — 401 wrong password, 409
 * address already registered, 400 that is already your address — and a generic
 * "couldn't change it" would leave them guessing which.
 */
export async function changeEmail(currentPassword: string, newEmail: string): Promise<void> {
  const res = await authFetch("/auth/email", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_email: newEmail }),
  });
  if (res.ok) return;
  // Two statuses carry no usable `detail` and would otherwise reach the user as
  // a bare code. 422 is Pydantic's EmailStr rejection — a LIST detail, which
  // extractErrorDetail deliberately will not render — and 429 is slowapi's own
  // envelope, which has no `detail` key at all. Both are the user's to act on,
  // so they get the same treatment requestPasswordReset already gives them.
  if (res.status === 422) throw new Error("Please enter a valid email address.");
  if (res.status === 429) {
    throw new Error("Too many attempts. Please wait a minute and try again.");
  }
  throw new Error(await extractErrorDetail(res, "Could not change your email address"));
}

// --- Access requests (admin triage of the public landing form) ---

export async function fetchAccessRequests(
  status?: AccessRequestStatus,
): Promise<AccessRequestListResponse> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await authFetch(`/admin/access-requests${qs}`);
  if (!res.ok) throw new Error(`Admin access requests failed: ${res.status}`);
  return res.json();
}

export async function updateAccessRequest(
  id: number,
  status: "handled" | "dismissed",
): Promise<AccessRequestItem> {
  const res = await authFetch(`/admin/access-requests/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not update the request"));
  return res.json();
}

export async function deleteAccessRequest(id: number): Promise<void> {
  const res = await authFetch(`/admin/access-requests/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not delete the request"));
}

// --- Invite redemption (unauthenticated self-register from an admin link) ---

export async function redeemInvite(
  token: string,
  email: string,
  password: string,
  /**
   * Passed through as the user actually left it, NOT hardcoded true. The form
   * already blocks submission when it is unticked, so sending a constant would
   * work — right up until a bug enables the button without the box, at which
   * point it would silently fabricate consent. Sending the real value means the
   * server's 422 is the backstop.
   */
  acceptTerms: boolean,
): Promise<void> {
  const res = await authFetch("/users/register-invite", {
    method: "POST",
    body: JSON.stringify({ token, email, password, accept_terms: acceptTerms }),
  });
  if (res.ok) return;
  // 400 = invalid/expired/used/revoked link (opaque), 409 = email taken,
  // 422 = weak password (Pydantic list), 429 = rate-limited.
  let detail: string | null = null;
  try {
    const parsed = await res.json();
    if (typeof parsed?.detail === "string") detail = parsed.detail;
    else if (Array.isArray(parsed?.detail) && typeof parsed.detail[0]?.msg === "string") {
      detail = parsed.detail[0].msg;
    }
  } catch {
    // non-JSON body — fall through to a status-based message
  }
  if (res.status === 429) {
    throw new Error("Too many attempts. Please wait a minute and try again.");
  }
  if (res.status === 409) {
    throw new Error(detail ?? "An account with that email already exists.");
  }
  if (res.status === 422) {
    throw new Error(
      detail ?? "Password must be at least 8 characters with an upper- and lower-case letter and a digit.",
    );
  }
  throw new Error(detail ?? `Could not create your account (${res.status}).`);
}

// --- User feedback: submit (authed) + admin moderation (403-gated server-side) ---

export async function submitFeedback(
  body: FeedbackCreateRequest,
): Promise<FeedbackSubmitResponse> {
  const res = await authFetch("/feedback", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (res.ok) return res.json();
  // The backend returns a friendly `detail` string on 422 (gate reject), 409
  // (duplicate), 429 (too many open), 503 (disabled) and 403 (demo); Pydantic 422s
  // carry a list detail. Surface a real reason rather than a bare status.
  let detail: string | null = null;
  try {
    const parsed = await res.json();
    if (typeof parsed?.detail === "string") detail = parsed.detail;
    else if (Array.isArray(parsed?.detail) && typeof parsed.detail[0]?.msg === "string") {
      detail = parsed.detail[0].msg;
    }
  } catch {
    // non-JSON body — fall through to a status-based message
  }
  throw new Error(detail ?? `Could not send your feedback (${res.status}).`);
}

export interface AdminFeedbackQuery {
  status?: FeedbackStatusFilter;
  kind?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAdminFeedback(
  query: AdminFeedbackQuery = {},
): Promise<AdminFeedbackListResponse> {
  const p = new URLSearchParams();
  if (query.status && query.status !== "all") p.set("status", query.status);
  if (query.kind) p.set("kind", query.kind);
  if (query.limit != null) p.set("limit", String(query.limit));
  if (query.offset != null) p.set("offset", String(query.offset));
  const qs = p.toString();
  const res = await authFetch(`/admin/feedback${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Admin feedback failed: ${res.status}`);
  return res.json();
}

export async function fetchAdminFeedbackDetail(id: number): Promise<AdminFeedbackDetail> {
  const res = await authFetch(`/admin/feedback/${id}`);
  if (!res.ok) throw new Error(`Admin feedback detail failed: ${res.status}`);
  return res.json();
}

export async function updateAdminFeedback(
  id: number,
  status: FeedbackModerationStatus,
): Promise<AdminFeedbackDetail> {
  const res = await authFetch(`/admin/feedback/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not update the report"));
  return res.json();
}

export async function retriageAdminFeedback(id: number): Promise<AdminFeedbackDetail> {
  const res = await authFetch(`/admin/feedback/${id}/retriage`, { method: "POST" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not re-run triage"));
  return res.json();
}

/** The money-mover: mark accepted, grant the €1 credit (if eligible), open a ticket.
 *  Idempotent server-side (never double-credits). */
export async function acceptAdminFeedback(id: number): Promise<AdminFeedbackDetail> {
  const res = await authFetch(`/admin/feedback/${id}/accept`, { method: "POST" });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not accept the report"));
  return res.json();
}

export async function mergeFridgeItems(
  items: StockItem[],
  generationId: number | null = null,
): Promise<StockItem[]> {
  // generation_id (from the scan) rides as a query param so the merge body
  // stays a bare item array; the server owner-checks it for edit telemetry.
  const qs = generationId != null ? `?generation_id=${generationId}` : "";
  const res = await authFetch(`/fridge/merge${qs}`, {
    method: "POST",
    body: JSON.stringify(items),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Fridge merge failed: ${res.status} - ${txt}`);
  }
  return res.json();
}
