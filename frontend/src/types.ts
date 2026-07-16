// src/types.ts

import type { MealType } from "./constants/mealTypes";

export type { MealType } from "./constants/mealTypes";

export type MeasurementSystem = "none" | "imperial" | "metric";
export type Variability = "traditional" | "experimental";
export type DietType = "balanced" | "high_protein" | "low_carb" | "vegetarian" | "vegan" | "baby_food";

export interface IngredientAmount {
  name: string;
  quantity_grams: number;
  is_spice?: boolean;
}

export interface MealPlanRequest {
  ingredients: IngredientAmount[];
  taste_preferences: string[];
  avoid_ingredients: string[];
  ingredients_to_use: string[];
  diet_type: DietType | null;
  meals_per_day: number;
  people_count: number;
  past_meals: string[];
  stock_only?: boolean;
  // Phase 3+: per-day slot override. Outer length must equal `days` query
  // param. Null/undefined = fall back to user.default_day_layout → meals_per_day.
  day_layouts?: MealType[][] | null;
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
}

export interface SingleDayPlan {
  meals: PlannedMeal[];
}

export interface MealPlanResponse {
  plan_id: number;
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
  status: PlanStatus;
  total_meals: number;
  cooked_meals: number;
  finished_at: string | null;
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
  diet_type: DietType | null;
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
}

export interface AuthState {
  userId: number | null;
  email: string;
  onboardingCompleted: boolean;
  isDemo: boolean;
  isAdmin: boolean;
  // null until /api/config resolves, then boolean. Using null as the
  // unresolved sentinel lets the UI avoid a flash of the wrong copy
  // (e.g. rendering a "closed alpha" notice before registration_enabled
  // resolves to true).
  demoEnabled: boolean | null;
  registrationEnabled: boolean | null;
  // Billing state, sourced from the same profile payload as the rest. null-ish
  // defaults ("none"/null/false) hold until the profile resolves.
  subscriptionStatus: SubscriptionStatus;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  isSubscribed: boolean;
  isComped: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setOnboardingCompleted: (value: boolean) => void;
  loginDemo: () => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
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

