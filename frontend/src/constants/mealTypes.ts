// Mirror of backend/app/core/meal_types.py — keep the two files in sync by hand.
// The backend's MealType enum is the authority; this file exists so the frontend
// can render dropdowns and labels without round-tripping through the API.

export const MEAL_TYPES = [
  "sweet_breakfast",
  "savory_breakfast",
  "brunch",
  "snack",
  "soup",
  "light_lunch",
  "main_course",
  "side_dish",
  "hot_dinner",
  "cold_dinner",
  "dessert",
] as const;

export type MealType = (typeof MEAL_TYPES)[number];

export const MEAL_TYPE_LABELS: Record<MealType, string> = {
  sweet_breakfast: "Sweet breakfast",
  savory_breakfast: "Savory breakfast",
  brunch: "Brunch",
  snack: "Snack",
  soup: "Soup",
  light_lunch: "Light lunch",
  main_course: "Main course",
  side_dish: "Side dish",
  hot_dinner: "Hot dinner",
  cold_dinner: "Cold dinner",
  dessert: "Dessert",
};

const LEGACY_MEAL_TYPE_LABELS: Record<string, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
};

// Resolve a label for any meal_type string. Prefer the server-provided localized
// label when present; fall back to the English enum label; last resort is a
// titlecased version of whatever the string is (covers legacy rows).
export function mealTypeLabel(mealType: string, serverLabel?: string | null): string {
  if (serverLabel && serverLabel.trim()) return serverLabel;
  if (mealType in MEAL_TYPE_LABELS) return MEAL_TYPE_LABELS[mealType as MealType];
  if (mealType in LEGACY_MEAL_TYPE_LABELS) return LEGACY_MEAL_TYPE_LABELS[mealType];
  return mealType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
