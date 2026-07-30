// Typical weight of ONE whole item, for showing "2 eggs" instead of "120 g".
//
// Display only. Grams remain the single stored quantity and the only thing any
// arithmetic touches — the FIFO fridge debit, cross-meal shopping aggregation
// and leftover portion scaling all read `quantity_grams` and are untouched by
// anything here. Nothing in this file can change what a plan buys or debits.
//
// Keyed on `canonical_name`, the lowercase-singular ENGLISH key the model
// supplies alongside the localized ingredient name. It has to be a separate key
// because `name` is written in the user's language, so a table keyed on names
// would only ever work in English — the same trap that left cook-mode timers
// dead in Czech (#318).
//
// TRUST BOUNDARY: `canonical_name` arrives from the client on the Cook Now,
// edit and favorite paths, not only from the LLM. So this is an exact lookup
// against the table below and nothing else: an unknown, absent or adversarial
// key takes the identical path and renders grams. There is no branch where an
// unrecognised value produces a number.
//
// The model proposes the NAME; the COUNT is derived here. That split is the
// point — a hallucinated count would be an unverifiable number the user reads,
// whereas a hallucinated name simply fails to match and falls back to grams.
//
// Weights are typical edible-portion weights for a medium item, of the kind
// USDA FoodData Central publishes as standard portions, rounded to 5 g. They
// are approximations by nature: a "medium onion" is a range, not a constant.
// PLAUSIBILITY_TOLERANCE below is what absorbs that — the table only has to be
// close enough to identify a whole-unit multiple, never to be exact.
export const PIECE_WEIGHTS_G: Readonly<Record<string, number>> = {
  // Eggs & dairy
  egg: 50,
  // Alliums
  onion: 110,
  "red onion": 110,
  shallot: 40,
  "garlic clove": 5,
  "spring onion": 15,
  leek: 90,
  // Citrus
  lemon: 100,
  lime: 65,
  orange: 130,
  // Fruit
  apple: 180,
  banana: 120,
  pear: 180,
  avocado: 150,
  kiwi: 75,
  peach: 150,
  // Vegetables
  potato: 175,
  "sweet potato": 130,
  carrot: 60,
  tomato: 120,
  "cherry tomato": 17,
  "bell pepper": 120,
  chilli: 15,
  cucumber: 200,
  courgette: 195,
  zucchini: 195,
  aubergine: 230,
  eggplant: 230,
  mushroom: 20,
  "corn cob": 90,
  // Protein
  "chicken breast": 175,
  "chicken thigh": 115,
  sausage: 75,
  "bacon rasher": 25,
  // Bakery & staples
  "bread slice": 30,
  tortilla: 45,
  "burger bun": 60,
  bagel: 100,
};

// How far a computed count may sit from a whole number and still be shown as
// one. Deliberately generous: real produce varies by variety and size, so the
// table's job is only to identify the multiple. 20% of one item means a 110 g
// onion entry still reads "1 onion" anywhere from 88 g to 132 g, and falls back
// to grams outside that — which is the honest answer for "half an onion".
const PLAUSIBILITY_TOLERANCE = 0.2;

// Above this, a piece count stops being useful ("47 eggs") and starts looking
// like a misparse. Grams read better at that scale anyway.
const MAX_PLAUSIBLE_PIECES = 24;

/**
 * Whole-item count for `grams` of `canonicalName`, or null when pieces do not
 * apply — unknown key, non-finite or non-positive grams, or an amount that is
 * not close enough to a whole number of items.
 *
 * Null is the safe answer and every uncertain case returns it: the caller shows
 * grams, which is always correct.
 */
export function pieceCount(
  canonicalName: string | null | undefined,
  grams: number,
): number | null {
  if (!canonicalName) return null;
  if (!Number.isFinite(grams) || grams <= 0) return null;

  // Object.hasOwn, not a bare index: the key is attacker-influenced, and
  // `PIECE_WEIGHTS_G["__proto__"]` or `["constructor"]` would otherwise return
  // an inherited object. The numeric guard below happens to reject those too,
  // but relying on that is a subtlety one refactor away from being a hole.
  if (!Object.hasOwn(PIECE_WEIGHTS_G, canonicalName)) return null;
  const perPiece = PIECE_WEIGHTS_G[canonicalName];
  if (!Number.isFinite(perPiece) || perPiece <= 0) return null;

  const exact = grams / perPiece;
  const nearest = Math.round(exact);
  if (nearest < 1 || nearest > MAX_PLAUSIBLE_PIECES) return null;
  // Relative to the count, so the allowance scales with how many items there
  // are rather than letting a 6-item error hide inside a large absolute slack.
  if (Math.abs(exact - nearest) > PLAUSIBILITY_TOLERANCE * nearest) return null;
  return nearest;
}

/**
 * How to render an amount: a piece count when one applies and the user asked
 * for pieces, otherwise rounded grams. Returns both so callers can keep the
 * exact grams visible somewhere (a title attribute), since the count is an
 * approximation and the grams are the real stored value.
 */
export function formatAmount(
  grams: number,
  canonicalName: string | null | undefined,
  showPieces: boolean,
): { text: string; exactGrams: string; isPieces: boolean } {
  const exactGrams = `${Math.round(grams)}g`;
  if (!showPieces) return { text: exactGrams, exactGrams, isPieces: false };

  const count = pieceCount(canonicalName, grams);
  if (count === null) return { text: exactGrams, exactGrams, isPieces: false };

  return { text: `${count} pcs`, exactGrams, isPieces: true };
}
