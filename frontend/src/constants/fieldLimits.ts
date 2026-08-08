/**
 * How many entries each free-text list field accepts.
 *
 * These MIRROR the `max_length` declared on the matching fields in
 * `backend/app/models/plan_models.py`. The server's `sanitize_input` validator
 * reads its cap from that declaration and silently truncates anything past it,
 * so a UI that let the user exceed it would discard their input with no error
 * and no log — which is exactly the bug these numbers exist to prevent.
 *
 * The `list field caps` CI job greps both sides and fails on drift. Change the
 * backend declaration and this file together, or CI will say so.
 */
export const FIELD_LIMITS = {
  tastePreferences: 20,
  avoidIngredients: 50,
  ingredientsToUse: 20,
} as const;
