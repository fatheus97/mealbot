// Mirror of backend/app/core/dietary.py — keep the two files in sync by hand.
// The backend's DietType / Allergen StrEnums are the authority; this file exists
// so the frontend can render the diet + allergen selectors and labels without
// round-tripping through the API. VALUES must match the backend exactly (they are
// the wire contract persisted in request_json); only add, never rename.

// Combinable dietary patterns. Order here is DISPLAY order (common choices first).
export const DIET_TYPES = [
  "vegetarian",
  "vegan",
  "pescatarian",
  "gluten_free",
  "dairy_free",
  "keto",
  "paleo",
  "mediterranean",
  "dash",
  "low_fodmap",
  "diabetic",
  "high_protein",
  "low_carb",
  "halal",
  "kosher",
  "balanced",
  "baby_food",
] as const;

export type DietType = (typeof DIET_TYPES)[number];

export const DIET_TYPE_LABELS: Record<DietType, string> = {
  vegetarian: "Vegetarian",
  vegan: "Vegan",
  pescatarian: "Pescatarian",
  gluten_free: "Gluten-free",
  dairy_free: "Dairy-free",
  keto: "Keto",
  paleo: "Paleo",
  mediterranean: "Mediterranean",
  dash: "DASH",
  low_fodmap: "Low-FODMAP",
  diabetic: "Diabetic / low-GI",
  high_protein: "High protein",
  low_carb: "Low carb",
  halal: "Halal",
  kosher: "Kosher",
  balanced: "Balanced",
  baby_food: "Baby food (6–12 mo)",
};

// The 14 EU-14 major allergens (EU FIC Reg. 1169/2011 Annex II).
export const ALLERGENS = [
  "cereals_with_gluten",
  "crustaceans",
  "eggs",
  "fish",
  "peanuts",
  "soybeans",
  "milk",
  "tree_nuts",
  "celery",
  "mustard",
  "sesame",
  "sulphites",
  "lupin",
  "molluscs",
] as const;

export type Allergen = (typeof ALLERGENS)[number];

export const ALLERGEN_LABELS: Record<Allergen, string> = {
  cereals_with_gluten: "Gluten (cereals)",
  crustaceans: "Crustaceans",
  eggs: "Eggs",
  fish: "Fish",
  peanuts: "Peanuts",
  soybeans: "Soy",
  milk: "Milk / dairy",
  tree_nuts: "Tree nuts",
  celery: "Celery",
  mustard: "Mustard",
  sesame: "Sesame",
  sulphites: "Sulphites",
  lupin: "Lupin",
  molluscs: "Molluscs",
};
