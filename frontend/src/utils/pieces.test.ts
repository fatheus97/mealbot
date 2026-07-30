import { describe, it, expect } from 'vitest';
import { PIECE_WEIGHTS_G, pieceCount, formatAmount } from './pieces';

describe('pieceCount', () => {
  it('converts a clean multiple into whole items', () => {
    expect(pieceCount('egg', 100)).toBe(2); // 50g each
    expect(pieceCount('egg', 50)).toBe(1);
    expect(pieceCount('onion', 220)).toBe(2); // 110g each
  });

  it('tolerates real-produce variation around the typical weight', () => {
    // A "medium onion" is a range, not a constant, so ±20% still reads as one.
    expect(pieceCount('onion', 95)).toBe(1);
    expect(pieceCount('onion', 130)).toBe(1);
  });

  it('falls back to grams when the amount is not a whole number of items', () => {
    // Half an onion is exactly the case where grams are the honest answer.
    expect(pieceCount('onion', 55)).toBeNull();
    expect(pieceCount('egg', 75)).toBeNull(); // 1.5 eggs
  });

  // The trust boundary: canonical_name reaches this from client-submitted
  // PlannedMeals (Cook Now / edit / favorite), not only from the LLM. Every
  // unrecognised value takes the same path and renders grams — there is no
  // branch where an unknown key produces a number.
  it('returns null for anything not in the table', () => {
    expect(pieceCount('flour', 500)).toBeNull();
    expect(pieceCount('definitely not a food', 100)).toBeNull();
    expect(pieceCount('', 100)).toBeNull();
    expect(pieceCount(null, 100)).toBeNull();
    expect(pieceCount(undefined, 100)).toBeNull();
    expect(pieceCount('__proto__', 100)).toBeNull();
    expect(pieceCount('constructor', 100)).toBeNull();
  });

  it('rejects non-finite and non-positive amounts', () => {
    expect(pieceCount('egg', 0)).toBeNull();
    expect(pieceCount('egg', -50)).toBeNull();
    expect(pieceCount('egg', NaN)).toBeNull();
    expect(pieceCount('egg', Infinity)).toBeNull();
  });

  it('gives up rather than showing an implausible pile of items', () => {
    // "47 eggs" reads like a misparse; grams are clearer at that scale.
    expect(pieceCount('egg', 50 * 24)).toBe(24);
    expect(pieceCount('egg', 50 * 25)).toBeNull();
    // Below one whole item is a fraction, not a count.
    expect(pieceCount('onion', 20)).toBeNull();
  });
});

describe('formatAmount', () => {
  it('shows grams when the preference is off, even for a countable', () => {
    const a = formatAmount(100, 'egg', false);
    expect(a.text).toBe('100g');
    expect(a.isPieces).toBe(false);
  });

  it('shows pieces when the preference is on and the amount maps cleanly', () => {
    const a = formatAmount(100, 'egg', true);
    expect(a.text).toBe('2 pcs');
    expect(a.isPieces).toBe(true);
    // The exact grams stay available — the count is an approximation, the
    // grams are the real stored quantity.
    expect(a.exactGrams).toBe('100g');
  });

  it('falls back to grams with the preference on but no clean mapping', () => {
    expect(formatAmount(500, 'flour', true).text).toBe('500g');
    expect(formatAmount(75, 'egg', true).text).toBe('75g');
    expect(formatAmount(240, null, true).text).toBe('240g');
  });

  it('rounds grams for display', () => {
    expect(formatAmount(123.4, null, true).text).toBe('123g');
  });
});

describe('the weight table', () => {
  it('is keyed the same way canonical_name is normalized', () => {
    // The backend lowercases and trims canonical_name, so a key that isn't
    // already in that form could never be matched.
    for (const key of Object.keys(PIECE_WEIGHTS_G)) {
      expect(key, `"${key}" must be lowercase and trimmed`).toBe(key.trim().toLowerCase());
    }
  });

  it('holds only plausible single-item weights', () => {
    for (const [key, grams] of Object.entries(PIECE_WEIGHTS_G)) {
      expect(Number.isFinite(grams), `${key} must be finite`).toBe(true);
      // A whole item people count out weighs more than a pinch and less than a
      // kilo; anything outside that is a typo, and a typo here silently
      // mis-counts someone's shopping list.
      expect(grams, `${key} = ${grams}g looks wrong`).toBeGreaterThanOrEqual(3);
      expect(grams, `${key} = ${grams}g looks wrong`).toBeLessThanOrEqual(500);
    }
  });
});
