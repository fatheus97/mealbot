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
}

export interface SingleRecipeResponse {
  recipe: PlannedMeal;
}

export type ScannedItemType = "ingredient" | "ready_to_eat";

export interface StockItem {
  name: string;
  quantity_grams: number;
  need_to_use: boolean;
  item_type?: ScannedItemType;
  expiration_date?: string | null;
}

// Server-side response of POST /api/auth/login (and /demo). Same shape as
// GET /api/users — the SPA stores the relevant fields and lets the user
// keep working without a follow-up profile fetch.
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
  default_day_layout: MealType[] | null;
}

export interface AuthState {
  userId: number | null;
  email: string;
  onboardingCompleted: boolean;
  isDemo: boolean;
  // null until /api/config resolves, then boolean. Using null as the
  // unresolved sentinel lets the UI avoid a flash of the wrong copy
  // (e.g. rendering a "closed alpha" notice before registration_enabled
  // resolves to true).
  demoEnabled: boolean | null;
  registrationEnabled: boolean | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setOnboardingCompleted: (value: boolean) => void;
  loginDemo: () => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
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
  // Preferred shape of a single day's meals. null = user hasn't set one;
  // plan generation falls back to the legacy meals_per_day counter.
  default_day_layout: MealType[] | null;
}

