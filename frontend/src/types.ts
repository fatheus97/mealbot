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

export interface MealHistoryItem {
  meal_entry_id: number;
  meal_plan_id: number;
  day_index: number;
  meal_index: number;
  name: string;
  meal_type: string;
  created_at: string;
}

export interface StockItem {
  name: string;
  quantity_grams: number;
  need_to_use: boolean;
}

export interface AuthResponse {
  user_id: number;
  created: boolean;
  onboarding_completed: boolean;
}

export interface UserProfile {
  id: number;
  email: string;

  name: string | null;
  description: string | null;
  country: string | null;

  measurement_system: MeasurementSystem;
  variability: Variability;
  include_spices: boolean;

  onboarding_completed: boolean;
}

