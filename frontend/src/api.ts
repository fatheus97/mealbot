// frontend/src/api.ts
import type {
  PlanNutrition,
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
  AuthLoginResponse,
  BillingPlan,
  PolicyNoticePreview,
  PolicyNoticeSendResponse,
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
  ScanSource,
  ScannedItemsResponse,
  SingleRecipeRequest,
  SingleRecipeResponse,
  StatGranularity,
  StockItem,
  UsageByUserResponse,
  UsageStatsResponse,
  UserProfile,
  WasteEntry,
  WasteRecordedResponse,
  DietaryProfile,
  DietaryProfileBody,
  Household,
  HouseholdInviteCreated,
  RestockStatus,
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

  // 403 = a gate refused: email not confirmed, or no current consent for diet
  // data. The profile this tab holds may be stale (consent withdrawn on another
  // device, a newer consent text deployed), which would leave the consent
  // checkbox hidden while the server keeps refusing. AuthContext re-reads the
  // profile on this event, so the UI catches up with whatever the server said.
  if (response.status === 403) {
    window.dispatchEvent(new Event("mealbot:forbidden"));
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
  data: Partial<Pick<UserProfile, "country" | "language" | "measurement_system" | "variability" | "include_spices" | "track_snacks" | "show_pieces" | "show_nutrition" | "need_to_use_enabled" | "onboarding_completed" | "default_day_layout">>
): Promise<UserProfile> {
  const res = await authFetch("/users", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Profile update failed: ${res.status}`);
  return res.json();
}

export async function scanReceipt(
  file: File,
  source: ScanSource,
  copy: RequestCopy,
): Promise<ScannedItemsResponse> {
  const formData = new FormData();
  formData.append("file", file);

  let res: Response;
  try {
    res = await authFetch(`/fridge/scan?source=${source}`, {
      method: "POST",
      body: formData,
    });
  } catch {
    // No Response at all (network down, aborted): the browser's own message
    // ("Failed to fetch", "Load failed") is English and tells the user nothing.
    throw new Error(copy.fallback);
  }
  if (res.status === 402) throw new PaywallError();
  if (res.status === 429) {
    // Two different 429s share this status. The usage cap
    // (deps.require_generation_budget) carries its sentence in `user_detail`
    // under `code: "usage_cap_reached"`; slowapi's per-minute limit carries
    // nothing a person should read, whatever shape its envelope has. So branch
    // on the code, never on whether a `detail` happens to be present.
    let detail: { code?: unknown; user_detail?: unknown } | null | undefined;
    try {
      detail = (await res.json())?.detail;
    } catch {
      // non-JSON body: the rate limit
    }
    if (detail?.code === "usage_cap_reached" && typeof detail.user_detail === "string") {
      throw new Error(detail.user_detail);
    }
    throw new Error(copy.rateLimited);
  }
  if (!res.ok) {
    // The email-confirmation gate makes 403 a ROUTINE state here, and its
    // detail ("Please confirm your email address…") is user-facing copy.
    throw new Error(await extractErrorDetail(res, copy.fallback));
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

export async function fetchPlanNutrition(planId: number): Promise<PlanNutrition> {
  const res = await authFetch(`/plan/${planId}/nutrition`);
  if (!res.ok) throw new Error(`Failed to load nutrition: ${res.status}`);
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
    throw new Error(await extractErrorDetail(res, "Recipe cook failed"));
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

// --- Policy-change notice email (admin "Notices" tab) ---

export async function fetchPolicyNotice(): Promise<PolicyNoticePreview> {
  const res = await authFetch("/admin/policy-notice");
  if (!res.ok) throw new Error(`Policy notice preview failed: ${res.status}`);
  return res.json();
}

/** Queue the notice. `confirmRecipients` is the eligible count the admin was
 *  shown; the server refuses (409, with the reason) if it no longer matches. */
export async function sendPolicyNotice(
  confirmRecipients: number,
): Promise<PolicyNoticeSendResponse> {
  const res = await authFetch("/admin/policy-notice/send", {
    method: "POST",
    body: JSON.stringify({ confirm_recipients: confirmRecipients }),
  });
  if (!res.ok) throw new Error(await adminErrorDetail(res, "Could not send the notice"));
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
/** The banner showed a version the server no longer asks for (a deploy landed
 *  while the tab was open). Nothing was recorded. */
export class TermsVersionStaleError extends Error {}

/**
 * Record "I agree" for the legal change the banner showed.
 *
 * Sends only the version; the server stamps its own clock and version. A 409
 * means that version is stale, which the caller handles by re-reading the
 * profile; anything else is a plain failure to retry.
 */
export async function acceptTermsVersion(version: string): Promise<AuthLoginResponse> {
  const res = await authFetch("/users/terms/accept", {
    method: "POST",
    body: JSON.stringify({ version }),
  });
  if (res.status === 409) throw new TermsVersionStaleError();
  if (!res.ok) throw new Error("Could not record your agreement.");
  return (await res.json()) as AuthLoginResponse;
}

/** The consent checkbox showed a text the server no longer asks for (a deploy
 *  landed while the tab was open). Nothing was recorded. */
export class HealthConsentStaleError extends Error {}

/**
 * Record explicit consent to process diets, allergens and ingredients to avoid.
 * Sends only the version of the sentence the checkbox showed; the server stamps
 * its own clock and version and answers 409 when that text is out of date.
 */
export async function grantHealthConsentRequest(version: string): Promise<AuthLoginResponse> {
  const res = await authFetch("/users/health-consent", {
    method: "POST",
    body: JSON.stringify({ version }),
  });
  if (res.status === 409) throw new HealthConsentStaleError();
  if (!res.ok) throw new Error(await extractErrorDetail(res, "Could not record your consent."));
  return (await res.json()) as AuthLoginResponse;
}

/** Withdraw that consent. The server also empties those fields in saved plans. */
export async function withdrawHealthConsentRequest(): Promise<AuthLoginResponse> {
  const res = await authFetch("/users/health-consent", { method: "DELETE" });
  if (!res.ok) throw new Error(await extractErrorDetail(res, "Could not withdraw your consent."));
  return (await res.json()) as AuthLoginResponse;
}

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

/**
 * The two sentences these calls may have to invent, passed in ALREADY
 * TRANSLATED by the component.
 *
 * `api.ts` runs outside React and cannot call `t()`, so any English literal in
 * here is English forever — `changeEmail` above has two, which is the bug this
 * shape avoids rather than the precedent it follows. Everything else the user
 * sees on these paths is a server `detail`, which the backend already localises.
 */
export interface RequestCopy {
  /** Shown on 429 — slowapi's envelope carries no `detail` to render. */
  rateLimited: string;
  /** Shown when the response body carries no usable `detail` at all. */
  fallback: string;
}

/**
 * Download everything the account owns as one JSON file.
 *
 * Goes through `authFetch` rather than a plain `<a download href="/api/…">`,
 * which would be less code: an anchor downloads whatever comes back, so a 401
 * or a 429 lands in the user's Downloads folder as a file full of error JSON,
 * and the silent-refresh retry never runs. Fetching first means a failure is a
 * message on screen and a success is still a real file.
 *
 * The filename comes from the server's Content-Disposition when present — it
 * carries the export date — with a static fallback for the case where a proxy
 * strips the header.
 */
export async function downloadMyData(copy: RequestCopy): Promise<void> {
  const res = await authFetch("/users/export");
  if (!res.ok) {
    // slowapi's 429 envelope has no `detail` key at all, so extractErrorDetail
    // has nothing to render. It is also the likeliest failure here (5/hour).
    if (res.status === 429) throw new Error(copy.rateLimited);
    throw new Error(await extractErrorDetail(res, copy.fallback));
  }
  const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = match?.[1] ?? "mealbot-export.json";
    a.click();
  } finally {
    // Deferred: revoking synchronously can beat the browser to reading the blob
    // in some engines, and the object would otherwise be pinned for the life of
    // the document — an export is the largest thing this app holds in memory.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

/**
 * Permanently delete the caller's own account.
 *
 * The server cancels the Stripe subscription BEFORE deleting and 503s if that
 * fails, so a failure here can mean "nothing happened, try again" — which is
 * why the detail is surfaced verbatim rather than collapsed into one message.
 * On success every cookie is cleared server-side; the caller is responsible for
 * dropping SPA state (there is no session left to refresh).
 */
export async function deleteAccount(
  currentPassword: string,
  copy: RequestCopy,
): Promise<void> {
  const res = await authFetch("/auth/delete-account", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword }),
  });
  if (res.ok) return;
  if (res.status === 429) throw new Error(copy.rateLimited);
  throw new Error(await extractErrorDetail(res, copy.fallback));
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

/**
 * Post "ate it / threw it out" answers.
 *
 * Separate from the fridge write on purpose: PUT /fridge replaces the whole
 * list, so the server cannot infer that an item was removed, let alone why.
 * Callers fire this AFTER the fridge edit is away — the answers are optional
 * metadata and must never be able to cost the user their edit.
 */
export async function recordWaste(entries: WasteEntry[]): Promise<WasteRecordedResponse> {
  const res = await authFetch(`/fridge/waste`, {
    method: "POST",
    body: JSON.stringify(entries),
  });
  if (!res.ok) throw new Error(`Waste capture failed: ${res.status}`);
  return res.json();
}

export async function mergeFridgeItems(
  items: StockItem[],
  generationIds: number[],
  copy: RequestCopy & { connectionLost: string },
): Promise<StockItem[]> {
  // One generation_id per scan rides as a repeated query param so the merge
  // body stays a bare item array; the server owner-checks each for telemetry.
  // ponytail: the server refuses more than 20 ids, so a longer list sends none
  // (that save's edit telemetry is skipped). A prefix would be compared with
  // the whole list and record corrections nobody made.
  const qs = new URLSearchParams(
    (generationIds.length > 20 ? [] : generationIds).map((id) => ["generation_id", String(id)]),
  ).toString();
  let res: Response;
  try {
    res = await authFetch(`/fridge/merge${qs ? `?${qs}` : ""}`, {
      method: "POST",
      body: JSON.stringify(items),
    });
  } catch {
    // No Response: the merge may have committed before the connection dropped,
    // and it is not idempotent, so "try again" could add everything twice.
    throw new Error(copy.connectionLost);
  }
  if (res.status === 429) throw new Error(copy.rateLimited);
  if (!res.ok) throw new Error(await extractErrorDetail(res, copy.fallback));
  return res.json();
}

// --- Start fresh prompt (docs/restock-design.md, "Return after an absence") ---

export async function fetchRestockStatus(): Promise<RestockStatus> {
  const res = await authFetch("/fridge/restock");
  if (!res.ok) throw new Error(`Restock status failed: ${res.status}`);
  return res.json();
}

/** Either answer to the prompt. A failure shows nothing: the prompt is already
 *  closed and stays closed for the session. */
export async function answerRestockPrompt(): Promise<RestockStatus> {
  const res = await authFetch("/fridge/restock/answer", { method: "POST" });
  if (!res.ok) throw new Error(`Restock answer failed: ${res.status}`);
  return res.json();
}

// --- Households (docs/household-design.md, "Join and leave") ---
//
// Every refusal here carries a server `detail` in the user's language; the copy
// covers only a 429 and a body without one (see RequestCopy).

export async function fetchHousehold(): Promise<Household> {
  const res = await authFetch("/household");
  if (!res.ok) throw new Error(`Household failed: ${res.status}`);
  return res.json();
}

export async function createHouseholdInvite(
  email: string,
  copy: RequestCopy,
): Promise<HouseholdInviteCreated> {
  const res = await authFetch("/household/invites", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  if (res.ok) return res.json();
  if (res.status === 429) throw new Error(copy.rateLimited);
  throw new Error(await extractErrorDetail(res, copy.fallback));
}

export async function revokeHouseholdInvite(id: number, copy: RequestCopy): Promise<void> {
  const res = await authFetch(`/household/invites/${id}`, { method: "DELETE" });
  if (res.ok) return;
  if (res.status === 429) throw new Error(copy.rateLimited);
  throw new Error(await extractErrorDetail(res, copy.fallback));
}

/** On success this account is in another household: reload the page. */
export async function joinHousehold(code: string, copy: RequestCopy): Promise<void> {
  const res = await authFetch("/household/join", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  if (res.ok) return;
  if (res.status === 429) throw new Error(copy.rateLimited);
  throw new Error(await extractErrorDetail(res, copy.fallback));
}

/** On success this account is in a household of its own: reload the page. */
export async function leaveHousehold(copy: RequestCopy): Promise<void> {
  const res = await authFetch("/household/leave", { method: "POST" });
  if (res.ok) return;
  if (res.status === 429) throw new Error(copy.rateLimited);
  throw new Error(await extractErrorDetail(res, copy.fallback));
}

export async function fetchDietaryProfile(): Promise<DietaryProfile | null> {
  const res = await authFetch("/users/dietary-profile");
  if (!res.ok) throw new Error(`Dietary profile failed: ${res.status}`);
  return res.json();
}

export async function saveDietaryProfile(
  body: DietaryProfileBody,
  copy: RequestCopy,
): Promise<DietaryProfile> {
  const res = await authFetch("/users/dietary-profile", {
    method: "PUT",
    body: JSON.stringify(body),
  });
  if (res.ok) return res.json();
  if (res.status === 429) throw new Error(copy.rateLimited);
  throw new Error(await extractErrorDetail(res, copy.fallback));
}

export async function deleteDietaryProfile(copy: RequestCopy): Promise<void> {
  const res = await authFetch("/users/dietary-profile", { method: "DELETE" });
  if (res.ok) return;
  if (res.status === 429) throw new Error(copy.rateLimited);
  throw new Error(await extractErrorDetail(res, copy.fallback));
}
