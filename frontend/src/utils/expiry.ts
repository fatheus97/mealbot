import type { StockItem } from "../types";
import { todayISO } from "./planDates";

/**
 * How far "still fine" pushes an item's expiry date.
 *
 * This is a RE-ASK INTERVAL, not a shelf-life claim: the stored date has just
 * been shown to be wrong, and we have no basis for a better one. A week is long
 * enough that finishing next week's plan doesn't re-ask about the same jar, and
 * short enough that the item doesn't silently drop out of expiry tracking —
 * which is what clearing the date (the other obvious option) would do.
 */
export const STILL_FINE_EXTENSION_DAYS = 7;

/**
 * Is this item PAST its expiry date?
 *
 * Strictly before today — an item whose date is today has not expired yet, and
 * prompting about it would be asking the user to judge food that is still
 * within its own stated life.
 *
 * Deliberately NARROWER than the fridge's `need_to_use` flag, which auto-ticks
 * at today+2 (see `fridge_service.get_fridge_items`) to nudge you to cook
 * something soon. "Use this up" and "is this still edible?" are different
 * questions; asking the second about food that is merely *approaching* its date
 * would train the user to click through.
 *
 * Both operands are ISO "YYYY-MM-DD", so a lexicographic compare IS a date
 * compare — no Date construction, no timezone shift.
 */
export function isExpired(item: StockItem): boolean {
  return item.expiration_date != null && item.expiration_date < todayISO();
}
