// Mirror of backend/app/core/dietary.py — keep the two files in sync by hand.
// The backend's DietType / Allergen StrEnums are the authority; this file exists
// so the frontend can render the diet + allergen selectors without
// round-tripping through the API. VALUES must match the backend exactly (they are
// the wire contract persisted in request_json); only add, never rename.
//
// VALUES only — no display labels. Those live in the i18n dictionary; see the
// note under DietType below.

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

// Display labels live in the i18n dictionary (`diet.*` / `allergen.*` in
// frontend/src/i18n/en.ts), not here — a Record<Enum, string> of English can
// only ever be English. i18n.test.ts asserts the keys and these lists stay in
// step, in both directions. VALUES above remain the wire contract: only add,
// never rename.

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

