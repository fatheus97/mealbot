// src/types.ts

export type MeasurementSystem = "none" | "imperial" | "metric";
export type Variability = "traditional" | "experimental";
export type DietType = "balanced" | "high_protein" | "low_carb" | "vegetarian" | "vegan";

export interface IngredientAmount {
  name: string;
  quantity_grams: number;
}

export interface MealPlanRequest {
  ingredients: IngredientAmount[];
  taste_preferences: string[];
  avoid_ingredients: string[];
  diet_type: DietType | null;
  meals_per_day: number;
  people_count: number;
  past_meals: string[];
}

export interface PlannedMeal {
  name: string;
  meal_type: "breakfast" | "lunch" | "dinner" | "snack" | string;
  uses_existing_ingredients: string[];
  ingredients: IngredientAmount[];
  steps: string[];
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
  rating: number | null;
}

export type ScannedItemType = "ingredient" | "ready_to_eat";

export interface StockItem {
  name: string;
  quantity_grams: number;
  need_to_use: boolean;
  item_type?: ScannedItemType;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: number;
  email: string;
  onboarding_completed: boolean;
}

export interface AuthState {
  userId: number | null;
  token: string | null; // <-- NEW: Added token to state
  email: string;
  onboardingCompleted: boolean; // <-- NEW: Track onboarding state
  login: (email: string, password: string) => Promise<LoginResponse>;
  logout: () => void;
  setOnboardingCompleted: (value: boolean) => void;
}

export interface UserProfile {
  id: number;
  email: string;
  country: string | null;
  measurement_system: MeasurementSystem;
  variability: Variability;
  include_spices: boolean;
  track_snacks: boolean;
  onboarding_completed: boolean;
}

