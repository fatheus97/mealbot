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
//
// MEAL_TYPE_LABELS survives here — unlike DIET_TYPE_LABELS / ALLERGEN_LABELS,
// which were deleted in #368 — because it is this function's FALLBACK, not a
// display table components read. The localized label comes from the model, so
// it is already in the user's recipe language; English is what remains when a
// row predates that field.
//
// A caller with NO server label to pass should read the dictionary directly
// (the `mealType.*` keys) rather than call this, or it renders English inside
// a translated UI. That is what the day-layout previews in MealPlanner and
// DayLayoutEditor do — they build from the user's own enum values, where no
// server label exists to prefer.
export function mealTypeLabel(mealType: string, serverLabel?: string | null): string {
  if (serverLabel && serverLabel.trim()) return serverLabel;
  if (mealType in MEAL_TYPE_LABELS) return MEAL_TYPE_LABELS[mealType as MealType];
  if (mealType in LEGACY_MEAL_TYPE_LABELS) return LEGACY_MEAL_TYPE_LABELS[mealType];
  return mealType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
