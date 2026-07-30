/**
 * First-touch acquisition attribution — IN MEMORY ONLY.
 *
 * Captures UTM params + referrer when a visitor lands and replays them into the
 * register call, so a signup can be traced back to the campaign that brought the
 * user — the one piece of funnel data that can't be reconstructed after the fact.
 *
 * ## Why this is not persisted
 *
 * This used to write to `localStorage`. ePrivacy treats *any* storage on the
 * visitor's terminal equipment the same way — localStorage is not exempt just
 * because it isn't a cookie — and remembering which ad brought someone here is
 * **marketing attribution, not strictly necessary** to deliver the service. It
 * was therefore the single thing on the whole site that would have required a
 * consent banner: the auth cookies (`mealbot_at`/`mealbot_rt`/`mealbot_csrf`)
 * are strictly necessary and exempt, and there is no third-party analytics
 * anywhere (the CSP is `default-src 'self'`, which blocks vendor beacons).
 *
 * Holding it in a module variable is not storage on the device, so nothing here
 * needs consent — and the site needs no cookie banner at all.
 *
 * ## What this costs
 *
 * Cross-session first-touch. "Arrives via an ad, leaves, comes back a week
 * later" is no longer credited to the ad — and that cross-session recognition
 * IS the part that needs consent, so losing it is the point, not a regression.
 * Within one page it still works, which covers the flow a campaign actually
 * uses: ad → landing → the register modal on that same page (#313).
 *
 * The module boundary is also a page boundary: `/` (landing) and `/app` (SPA)
 * are separate documents, so navigating between them starts a fresh capture.
 *
 * **If campaigns ever launch and cross-session first-touch is genuinely needed,
 * the fix is a consent gate, not quietly restoring the write.** Registration is
 * closed today and nothing reads this yet, so persisting it would be a legal
 * obligation bought with no benefit.
 */

export interface Attribution {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  referrer?: string;
}

// Mirror the backend caps (UserCreate truncates too, but trimming here keeps
// the payload small).
const UTM_CAP = 200;
const REFERRER_CAP = 500;

/** First-touch for THIS document. Deliberately not persisted — see above. */
let captured: Attribution | null = null;

/** The key the old persisted version wrote. Only ever removed, never read. */
const LEGACY_STORAGE_KEY = "mealbot_attribution";

function clean(value: string | null, cap: number): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return trimmed.slice(0, cap);
}

/**
 * Read the current URL's UTM params + referrer and, if anything is present AND
 * nothing is captured yet, keep it. Safe to call on every load — a no-op once
 * something is held (first-touch) or when there's nothing to capture (direct
 * visit with no referrer). Never throws.
 */
export function captureAttribution(): void {
  // Existing visitors still hold the key the persisted version wrote. We no
  // longer read it, so leaving it would mean holding data on someone's device
  // for no reason — clear it once, on the way past. Best-effort: localStorage
  // can throw in private mode.
  try {
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    /* ignore */
  }

  if (captured) return; // first-touch wins

  const params = new URLSearchParams(window.location.search);
  const next: Attribution = {};
  const source = clean(params.get("utm_source"), UTM_CAP);
  const medium = clean(params.get("utm_medium"), UTM_CAP);
  const campaign = clean(params.get("utm_campaign"), UTM_CAP);
  const referrer = clean(document.referrer || null, REFERRER_CAP);
  if (source) next.utm_source = source;
  if (medium) next.utm_medium = medium;
  if (campaign) next.utm_campaign = campaign;
  if (referrer) next.referrer = referrer;

  // Nothing worth recording (direct visit, no referrer) → leave it unset so a
  // later UTM'd visit in the same document can still be the first touch.
  if (Object.keys(next).length === 0) return;
  captured = next;
}

/** The first-touch attribution for this page, or an empty object. Never throws. */
export function getStoredAttribution(): Attribution {
  return captured ? { ...captured } : {};
}

/** Test-only: clear the module-level capture between cases. */
export function __resetAttributionForTests(): void {
  captured = null;
}
