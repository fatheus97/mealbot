// src/types.ts

import type { MealType } from "./constants/mealTypes";
import type { Allergen, DietType } from "./constants/dietary";

export type { MealType } from "./constants/mealTypes";
export type { Allergen, DietType } from "./constants/dietary";

export type MeasurementSystem = "none" | "imperial" | "metric";
export type Variability = "traditional" | "experimental";

export interface IngredientAmount {
  name: string;
  quantity_grams: number;
  is_spice?: boolean;
  // Lowercase-singular ENGLISH lookup key for the piece-weight table, set only
  // for countable whole items. `name` is in the user's language, so it can't be
  // the key. Absent on plans generated before the field existed — those simply
  // show grams. See utils/pieces.ts.
  canonical_name?: string | null;
}

export interface MealPlanRequest {
  ingredients: IngredientAmount[];
  taste_preferences: string[];
  avoid_ingredients: string[];
  ingredients_to_use: string[];
  // Combinable dietary patterns + structured allergens (dietary differentiator).
  // The legacy single `diet_type` is optional and no longer sent by the client;
  // the backend derives it from diet_types for backward-compat. Both new lists
  // are optional at the type level (backend defaults them to []).
  diet_types?: DietType[];
  allergens?: Allergen[];
  diet_type?: DietType | null;
  meals_per_day: number;
  people_count: number;
  past_meals: string[];
  stock_only?: boolean;
  // Phase 3+: per-day slot override. Outer length must equal `days` query
  // param. Null/undefined = fall back to user.default_day_layout → meals_per_day.
  day_layouts?: MealType[][] | null;
}

// Pointer to the meal a leftover was cooked as part of. 0-BASED, addressing
// positions inside MealPlanResponse.days — mirrors the backend LeftoverRef.
export interface LeftoverRef {
  day_index: number;
  meal_index: number;
}

/** One allergen the user's own edit reintroduced. A warning, never a block. */
export interface AllergenWarning {
  allergen: string;
  label: string;
  /** Ingredient name, or the step text when `source` is "step". */
  ingredient: string;
  source: "ingredient" | "step";
}

export interface PlannedMeal {
  name: string;
  // Server returns the strict MealType enum on freshly-generated meals, but
  // historical rows may carry legacy values ("breakfast" etc.) — keep the
  // string fallback so old plans still render.
  meal_type: MealType | string;
  meal_type_label?: string;
  ingredients: IngredientAmount[];
  steps: string[];
  total_time_minutes?: number | null;
  // Set only by the server when this meal is a reheat of an earlier one in the
  // same plan; null/absent for an ordinary meal. Optional so plans fetched
  // before the field existed still parse.
  leftover_of?: LeftoverRef | null;
}

export interface SingleDayPlan {
  meals: PlannedMeal[];
}

export interface MealPlanResponse {
  plan_id: number;
  // Real-world date of Day 1 as "YYYY-MM-DD" (null = unscheduled). Day N falls
  // on start_date + (N - 1). See utils/planDates.
  start_date: string | null;
  days: SingleDayPlan[];
  shopping_list: IngredientAmount[];
}

export interface FrozenMeal {
  day_index: number;
  meal_index: number;
}

export interface RegeneratePlanRequest {
  frozen_meals: FrozenMeal[];
}

// Body for PATCH /api/plan/{id}/days/{day}/meals/{meal}. meal_type is not
// editable — the endpoint preserves the existing slot — so it's absent here.
export interface MealEditRequest {
  name: string;
  ingredients: IngredientAmount[];
  steps: string[];
  total_time_minutes?: number | null;
}

export interface MealHistoryItem {
  meal_entry_id: number;
  meal_plan_id: number;
  day_index: number;
  meal_index: number;
  name: string;
  meal_type: string;
  created_at: string;
}

export type PlanStatus = "planned" | "active" | "cooked" | "finished";

export interface MealPlanSummary {
  id: number;
  created_at: string;
  days: number;
  meals_per_day: number;
  people_count: number;
  // Scheduled real-world date of Day 1 as "YYYY-MM-DD" (null = unscheduled).
  start_date: string | null;
  status: PlanStatus;
  total_meals: number;
  cooked_meals: number;
  finished_at: string | null;
}

// Result of PATCH /api/plan/{id} — the plan's new (possibly cleared) schedule.
export interface PlanScheduleResponse {
  plan_id: number;
  start_date: string | null;
}

// GET /api/plan/calendar — scheduled plans overlapping a window, each expanded
// into per-day cells the calendar places on the grid.
// One meal on a calendar day. An OBJECT, not a bare name — a leftover needs a
// marker and its provenance. `source_date` is resolved server-side because the
// source day can fall outside the rendered month; nullable, so the UI degrades
// to an unadorned marker rather than breaking.
export interface CalendarMeal {
  name: string;
  is_leftover: boolean;
  source_date: string | null; // "YYYY-MM-DD"
  source_name: string | null;
}

export interface CalendarDay {
  date: string; // "YYYY-MM-DD"
  day_index: number; // 1-based day within the plan
  meals: CalendarMeal[];
}
export interface CalendarPlanEntry {
  plan_id: number;
  start_date: string;
  status: PlanStatus;
  days: CalendarDay[];
}
export interface CalendarResponse {
  plans: CalendarPlanEntry[];
}

export interface FinishPlanResponse {
  status: "finished";
  finished_at: string;
  returned_meals: number;
}

export interface MealEntrySummary {
  id: number;
  day_index: number;
  meal_index: number;
  name: string;
  meal_type: string;
  cooked_at: string | null;
  is_favorite: boolean;
}

export interface CookbookItem {
  meal_entry_id: number;
  name: string;
  meal_type: string;
  meal_type_label: string;
  total_time_minutes: number | null;
  ingredients: IngredientAmount[];
  steps: string[];
  created_at: string;
  cooked_at: string | null;
}

export interface CookbookListResponse {
  total: number;
  items: CookbookItem[];
}

export interface CookbookCountResponse {
  count: number;
}

export interface FavoriteRecipeRequest {
  meal_type: MealType;
  people_count: number;
  recipe: PlannedMeal;
  // id from the /recipe/generate response, echoed back for edit telemetry.
  generation_id: number | null;
}

// Phase 4: Cook Now request/response
export interface SingleRecipeRequest {
  meal_type: MealType;
  diet_types?: DietType[];
  allergens?: Allergen[];
  diet_type?: DietType | null;
  people_count: number;
  taste_preferences: string[];
  avoid_ingredients: string[];
  ingredients_to_use: string[];
  stock_only: boolean;
  note: string | null;
}

export interface CookRecipeRequest extends SingleRecipeRequest {
  recipe: PlannedMeal;
  // id from the /recipe/generate response, echoed back for edit telemetry.
  generation_id: number | null;
}

export interface SingleRecipeResponse {
  recipe: PlannedMeal;
  generation_id: number | null;
}

export type ScannedItemType = "ingredient" | "ready_to_eat";

export interface StockItem {
  name: string;
  quantity_grams: number;
  need_to_use: boolean;
  item_type?: ScannedItemType;
  expiration_date?: string | null;
}

// A per-user "always have" pantry staple (salt, oil, flour…). Name-only — its
// job is to be excluded from generated shopping lists. Mirrors PantryStapleDTO.
export interface PantryStaple {
  name: string;
}

// Response of POST /api/fridge/scan. generation_id is echoed back on merge
// (as a query param) for edit telemetry; null on the demo path.
export interface ScannedItemsResponse {
  items: StockItem[];
  generation_id: number | null;
}

// Server-side response of POST /api/auth/login (and /demo). Same shape as
// GET /api/users — the SPA stores the relevant fields and lets the user
// keep working without a follow-up profile fetch.
// Loose string (mirrors Stripe's subscription.status, which the backend stores
// verbatim). The known values we render specially are the four below; anything
// else falls through to the generic "not subscribed" path.
export type SubscriptionStatus =
  | "none"
  | "trialing"
  | "active"
  | "past_due"
  | "canceled"
  | string;

export interface AuthLoginResponse {
  id: number;
  email: string;
  country: string | null;
  language: string;
  measurement_system: MeasurementSystem;
  variability: Variability;
  include_spices: boolean;
  track_snacks: boolean;
  show_pieces: boolean;
  onboarding_completed: boolean;
  is_demo: boolean;
  is_admin: boolean;
  default_day_layout: MealType[] | null;
  // Billing (mirror of Stripe). is_subscribed is the server-computed entitlement
  // the SPA gates paid UI on; the raw status + period end drive the banner copy.
  subscription_status: SubscriptionStatus;
  current_period_end: string | null;
  // True once canceled but still active until current_period_end (status stays
  // trialing/active) — drives "ends" vs "renews" wording.
  cancel_at_period_end: boolean;
  is_subscribed: boolean;
  // Complimentary ("friendlist") access — the SPA hides subscription billing UI.
  is_comped: boolean;
  // Whether the address has been confirmed. Drives the confirm-your-email
  // banner and the disabled generate controls; the server's 403 on
  // generation/checkout is only the backstop, exactly as is_subscribed relates
  // to the 402. Optional so a pre-verification cached payload (or a test mock
  // without the field) degrades to "verified" rather than nagging wrongly.
  email_verified?: boolean;
}

/** Subscription plan the user can pick at checkout. */
export type BillingPlan = "monthly" | "annual";

export interface AuthState {
  userId: number | null;
  email: string;
  onboardingCompleted: boolean;
  // Mirrored profile display preference — see utils/pieces.ts. Lives here so a
  // leaf renderer can read it without its own react-query subscription.
  showPieces: boolean;
  isDemo: boolean;
  isAdmin: boolean;
  // null until /api/config resolves, then boolean. Using null as the
  // unresolved sentinel lets the UI avoid a flash of the wrong copy
  // (e.g. rendering a "closed alpha" notice before registration_enabled
  // resolves to true).
  demoEnabled: boolean | null;
  registrationEnabled: boolean | null;
  // Whether the annual plan is offered at checkout (from /config). Defaults false
  // (monthly-only) until config resolves, so the paywall never shows a toggle that
  // would 400 on submit.
  annualBillingAvailable: boolean;
  // Billing state, sourced from the same profile payload as the rest. null-ish
  // defaults ("none"/null/false) hold until the profile resolves.
  subscriptionStatus: SubscriptionStatus;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  isSubscribed: boolean;
  isComped: boolean;
  // False only once the profile has resolved AND says unconfirmed — defaults
  // true so a slow /users call never flashes a "confirm your email" nag at
  // someone who already has.
  emailVerified: boolean;
  // Re-send the confirmation link to the caller's own address. Always resolves
  // (the endpoint is 204 even when already verified or inside the cooldown).
  resendVerification: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setOnboardingCompleted: (value: boolean) => void;
  loginDemo: () => Promise<void>;
  register: (email: string, password: string, acceptTerms: boolean) => Promise<void>;
  // Redeem an admin invite token: create the account (bypassing the closed
  // registration gate) then auto-login, so the invitee lands signed in.
  registerViaInvite: (token: string, email: string, password: string, acceptTerms: boolean) => Promise<void>;
  // Re-fetch /users to re-sync subscription state (used after returning from
  // Stripe Checkout, where the webhook may land a beat after the redirect).
  refreshProfile: () => Promise<void>;
}

export interface UserProfile {
  id: number;
  email: string;
  country: string | null;
  language: string;
  measurement_system: MeasurementSystem;
  variability: Variability;
  include_spices: boolean;
  track_snacks: boolean;
  show_pieces: boolean;
  onboarding_completed: boolean;
  is_admin: boolean;
  // Preferred shape of a single day's meals. null = user hasn't set one;
  // plan generation falls back to the legacy meals_per_day counter.
  default_day_layout: MealType[] | null;
}

// --- Admin stats API (mirror backend app/models/admin_schemas.py) ---

export type StatGranularity = "day" | "week" | "month";

export interface SurfaceCount {
  surface: string;
  count: number;
}

export interface OverviewStats {
  total_users: number;
  active_users_30d: number;
  demo_users: number;
  admin_users: number;
  llm_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  generations_by_surface: SurfaceCount[];
}

export interface UsageBucket {
  period: string; // ISO date
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface SurfaceUsageAgg {
  surface: string;
  calls: number;
  total_tokens: number;
}

export interface ProviderUsageAgg {
  provider: string;
  calls: number;
  total_tokens: number;
}

export interface UsageStatsResponse {
  from_date: string;
  to_date: string;
  granularity: string;
  series: UsageBucket[];
  by_surface: SurfaceUsageAgg[];
  by_provider: ProviderUsageAgg[];
}

export interface UserUsageAgg {
  user_id: number;
  email: string;
  calls: number;
  total_tokens: number;
  avg_tokens_per_call: number;
}

export interface UsageByUserResponse {
  users_with_usage: number;
  avg_tokens_per_user: number;
  top_users: UserUsageAgg[];
}

export interface ActivityBucket {
  period: string; // ISO date
  generations: number;
}

export interface ActivityStatsResponse {
  from_date: string;
  to_date: string;
  granularity: string;
  series: ActivityBucket[];
  by_surface: SurfaceCount[];
}

// --- Activation funnel (mirror backend admin_schemas FunnelStatsResponse) ---

export interface FunnelStage {
  key: string;
  label: string;
  count: number;
}

export interface FunnelBySource {
  source: string;
  signed_up: number;
  generated: number;
  confirmed: number;
  cooked: number;
  paid: number;
}

export interface FunnelStatsResponse {
  stages: FunnelStage[];
  by_source: FunnelBySource[];
}

// --- Revenue & VAT (mirror backend admin_schemas RevenueStats) ---

export interface ThresholdProgress {
  key: "eu_oss" | "cz_domestic" | string;
  label: string;
  current: number;
  threshold: number;
  unit: "EUR" | "CZK" | string;
  pct: number; // current/threshold, uncapped
  note: string;
}

export interface CountryRevenue {
  country: string | null;
  is_eu: boolean;
  amount_cents: number;
  sales: number;
}

export interface SaleRow {
  occurred_at: string;
  amount_cents: number;
  currency: string;
  country: string | null;
  is_business: boolean;
}

export interface RevenueStats {
  currency: string;
  total_cents: number;
  sales_count: number;
  eu_cross_border_b2c_cents: number;
  cz_domestic_cents: number;
  non_eur_sales_count: number;
  eur_czk_rate: number;
  thresholds: ThresholdProgress[];
  by_country: CountryRevenue[];
  recent: SaleRow[];
}

// --- User management (mirror backend admin_schemas AdminUserRead) ---

export interface AdminUser {
  id: number;
  email: string;
  created_at: string;
  is_active: boolean;
  is_admin: boolean;
  is_demo: boolean;
  is_comped: boolean;
  onboarding_completed: boolean;
  country: string | null;
  subscription_status: string;
  current_period_end: string | null;
  /** Confirmed email address. False ⇒ the user is 403'd out of generation and
   *  checkout until they follow the link (or an admin force-verifies them).
   *  Demo accounts always read true — no inbox to confirm. */
  email_verified: boolean;
}

export interface AdminUserListResponse {
  total: number;
  limit: number;
  offset: number;
  users: AdminUser[];
}

/** `unverified` filters on email confirmation, not enablement — orthogonal to
 *  active/disabled, but sharing the select (same precedent as the role filter,
 *  whose values are likewise independent booleans). */
export type AdminUserStatusFilter = "all" | "active" | "disabled" | "unverified";
export type AdminUserRoleFilter = "all" | "admin" | "demo" | "comped";

/** Partial flag update sent to PATCH /admin/users/{id}. */
export interface AdminUserUpdate {
  is_active?: boolean;
  is_admin?: boolean;
  is_comped?: boolean;
}

// --- Admin invite links ---

export type InviteStatus = "live" | "used" | "expired" | "revoked";

/** Body for POST /admin/invites. All optional — the server defaults comp to true
 *  and the TTL to invite_token_expire_hours. */
export interface InviteCreateRequest {
  note?: string | null;
  is_comped?: boolean;
  expires_in_hours?: number | null;
}

/** Response of POST /admin/invites — the freshly minted link. `invite_url`
 *  carries the plaintext token and is shown to the admin exactly once. */
export interface InviteCreateResponse {
  id: number;
  invite_url: string;
  expires_at: string;
  is_comped: boolean;
  note: string | null;
}

export interface InviteListItem {
  id: number;
  note: string | null;
  is_comped: boolean;
  status: InviteStatus;
  created_at: string;
  expires_at: string;
  redeemed_by_email: string | null;
}

export interface InviteListResponse {
  invites: InviteListItem[];
}

// --- Access requests (public landing form → admin queue) ---

export type AccessRequestStatus = "pending" | "handled" | "dismissed";

export interface AccessRequestItem {
  id: number;
  email: string;
  message: string;
  status: AccessRequestStatus;
  created_at: string;
  handled_at: string | null;
  /** Whether this address already has an account. Admin-only signal — the
   *  public submit endpoint deliberately never reveals it. */
  has_account: boolean;
}

export interface AccessRequestListResponse {
  requests: AccessRequestItem[];
  /** Pending total regardless of the active filter, for the tab badge. */
  pending_count: number;
}

// --- User feedback (bug reports / feature requests) ---

export type FeedbackKind = "bug" | "feature" | "other";

/** Body for POST /feedback (authenticated). `page` is optional client context. */
export interface FeedbackCreateRequest {
  kind: FeedbackKind;
  message: string;
  page?: string | null;
}

export interface FeedbackSubmitResponse {
  id: number;
  status: string;
}

/** Moderation states an admin may SET (the 6a subset — "accepted" is the
 *  money-moving 6b action and isn't offered here). */
export type FeedbackModerationStatus = "new" | "reviewing" | "rejected" | "spam";

/** The advisory LLM triage attached to a report (admin-only). Never authoritative —
 *  a human reviews every report; this only pre-sorts the queue. */
export interface FeedbackTriage {
  is_actionable: boolean;
  type: "bug" | "feature" | "question" | "praise" | "spam" | "other";
  severity: "low" | "medium" | "high";
  title: string;
  summary: string;
  repro: string | null;
  dedupe_hint: string | null;
}

/** One row in the admin moderation queue (list projection — preview, not the full
 *  body; denormalized triage summary fields). */
export interface AdminFeedbackItem {
  id: number;
  user_id: number;
  user_email: string | null;
  kind: string;
  status: string;
  created_at: string;
  preview: string;
  triage_status: string | null;
  triage_is_actionable: boolean | null;
  triage_type: string | null;
  triage_severity: string | null;
  triage_title: string | null;
}

export interface AdminFeedbackListResponse {
  total: number;
  limit: number;
  offset: number;
  items: AdminFeedbackItem[];
}

/** Full report for the admin detail view: verbatim body + parsed advisory triage. */
export interface AdminFeedbackDetail {
  id: number;
  user_id: number;
  user_email: string | null;
  kind: string;
  message: string;
  page: string | null;
  status: string;
  created_at: string;
  triage_status: string | null;
  triage: FeedbackTriage | null;
  reviewed_by_admin_id: number | null;
  reviewed_at: string | null;
  // 6b: credit + ticket outcomes (set on admin Accept).
  credit_cents: number | null;
  credit_granted_at: string | null;
  ticket_url: string | null;
}

/** Status filter for the admin feedback list. "accepted" is read-only here (the
 *  queue can show it, but only the 6b money slice sets it). */
export type FeedbackStatusFilter =
  | "all"
  | "new"
  | "reviewing"
  | "accepted"
  | "rejected"
  | "spam";


/**
 * PATCH meal response: the saved meal plus anything the allergen screen found.
 * The backend subclasses PlannedMeal, so this is PlannedMeal + one array.
 */
export interface MealEditResponse extends PlannedMeal {
  allergen_warnings?: AllergenWarning[];
}
