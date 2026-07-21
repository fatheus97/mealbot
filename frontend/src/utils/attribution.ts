/**
 * First-touch acquisition attribution.
 *
 * Captures UTM params + referrer from the URL the FIRST time a visitor lands,
 * persists them to localStorage, and replays them into the register call so a
 * signup can be traced back to the campaign that brought the user — the one
 * piece of funnel data that can't be reconstructed after the fact.
 *
 * **First-touch, not last-touch:** we only write if nothing is stored yet, so a
 * user who arrives via an ad, leaves, and comes back directly a week later is
 * still credited to the ad. The capture must run early (app mount), before any
 * navigation drops the query string.
 */

const STORAGE_KEY = "mealbot_attribution";

export interface Attribution {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  referrer?: string;
}

// Mirror the backend caps (UserCreate truncates too, but trimming here keeps
// localStorage tidy and the payload small).
const UTM_CAP = 200;
const REFERRER_CAP = 500;

function clean(value: string | null, cap: number): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return trimmed.slice(0, cap);
}

/**
 * Read the current URL's UTM params + referrer and, if anything is present AND
 * nothing is already stored, persist them. Safe to call on every load — it's a
 * no-op once something is stored (first-touch) or when there's nothing to
 * capture (direct visit with no referrer). Never throws.
 */
export function captureAttribution(): void {
  try {
    if (window.localStorage.getItem(STORAGE_KEY)) return; // first-touch wins

    const params = new URLSearchParams(window.location.search);
    const captured: Attribution = {};
    const source = clean(params.get("utm_source"), UTM_CAP);
    const medium = clean(params.get("utm_medium"), UTM_CAP);
    const campaign = clean(params.get("utm_campaign"), UTM_CAP);
    const referrer = clean(document.referrer || null, REFERRER_CAP);
    if (source) captured.utm_source = source;
    if (medium) captured.utm_medium = medium;
    if (campaign) captured.utm_campaign = campaign;
    if (referrer) captured.referrer = referrer;

    // Nothing worth recording (direct visit, no referrer) → leave it unset so a
    // later UTM'd visit in the same browser can still be the first touch.
    if (Object.keys(captured).length === 0) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(captured));
  } catch {
    // localStorage can throw (private mode / quota). Attribution is best-effort;
    // never let it break app startup or a signup.
  }
}

/** The stored first-touch attribution, or an empty object. Never throws. */
export function getStoredAttribution(): Attribution {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Attribution;
    // Defensive: only pass through known string fields (a tampered/legacy blob
    // shouldn't inject arbitrary keys into the register payload).
    const out: Attribution = {};
    if (typeof parsed.utm_source === "string") out.utm_source = parsed.utm_source;
    if (typeof parsed.utm_medium === "string") out.utm_medium = parsed.utm_medium;
    if (typeof parsed.utm_campaign === "string") out.utm_campaign = parsed.utm_campaign;
    if (typeof parsed.referrer === "string") out.referrer = parsed.referrer;
    return out;
  } catch {
    return {};
  }
}
