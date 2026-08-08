import { landingCopy } from "./copy";

// Registration-aware CTA enhancement for the static marketing landing (`/`).
// Progressively enhances a safe static baseline — never the other way around:
// the HTML already renders a working "Request access" (an in-page #access
// anchor to the request form, with a noscript mailto fallback) + "Log in"
// CTA with no JS at all, and this module only ever mutates it IN PLACE once
// `GET /api/config` resolves. A fetch failure or a slow network leaves the
// baseline exactly as authored (fail-safe), mirroring AuthContext's own
// fail-to-false pattern for the same flags.
//
// Pure logic lives here so it's testable without a real DOM; main.ts (the
// Vite entry) does the getElementById wiring and calls into these.

// Optional fields, not required — this is untyped JSON off the wire, and the
// AuthContext.tsx consumer of the same /api/config response treats it the
// same defensive way (an inline type with the same three optional booleans,
// coerced via Boolean()). A required-boolean shape would claim a guarantee
// the runtime value doesn't actually have.
export interface PublicConfig {
  demo_mode?: boolean;
  registration_enabled?: boolean;
  annual_billing_available?: boolean;
}

export const LOGGED_IN_HINT_KEY = "mealbot_user_id";

/**
 * A visitor at `/` carrying a reset_token/invite/billing param arrived via a
 * stale link still pointing at the root (pre-landing-page emails/redirects).
 * They need the actual app + modal, not the marketing pitch — forward them.
 * Returns null (no redirect) for a plain visit, including one carrying only
 * utm_* params, which the caller should instead thread onto the /app links.
 */
export function paramForwardTarget(search: string): string | null {
  const params = new URLSearchParams(search);
  if (params.has("reset_token") || params.has("invite") || params.has("billing")) {
    return `/app${search}`;
  }
  return null;
}

/**
 * A logged-in-looking bookmark of `/` (the synchronous render-hint AuthContext
 * also uses) should land in the app, not re-see the marketing pitch on every
 * visit.
 */
export function loggedInRedirectTarget(hasUserIdHint: boolean, search: string): string | null {
  return hasUserIdHint ? `/app${search}` : null;
}

/**
 * Thread the current query string onto every /app-bound link — independent
 * of whether `/api/config` has resolved yet — so campaign attribution
 * (utm_* — see utils/attribution.ts, which runs once the visitor actually
 * reaches the SPA) isn't silently dropped by the `/` -> `/app` hop.
 */
export function forwardSearchOnAppLinks(
  els: { login: HTMLAnchorElement | null; demo: HTMLAnchorElement | null },
  search: string,
): void {
  if (els.login) els.login.href = `/app${search}`;
  if (els.demo) els.demo.href = `/app${search}`;
}

/** The class the demo button carries while reserved-but-invisible — see the
 * #cta-box comment in index.html for why this is visibility, not display. */
const RESERVED_CLASS = "cta-reserved";

/**
 * Apply the fetched config to the CTA. `config === null` (fetch pending or
 * failed) is a deliberate no-op — the static baseline stays exactly as
 * authored, so there is never a flash between "unknown" and "closed" states.
 * Only ever mutates the BUTTONS (text/href/the reserved class) — never the
 * #cta-box container itself, and never removes/adds a button to the flow —
 * so this can never shift layout (CLS). Revealing the demo button flips
 * `.cta-reserved` off rather than toggling `hidden` (display:none), which
 * would change how many boxes flex-wrap lays out and resize the container.
 */
export function applyConfig(
  config: PublicConfig | null,
  els: { primary: HTMLAnchorElement | null; demo: HTMLAnchorElement | null },
  search: string,
): void {
  if (config === null) return;
  if (config.registration_enabled === true && els.primary) {
    els.primary.textContent = landingCopy().ctaGetStarted;
    els.primary.href = `/app${search}`;
  }
  if (config.demo_mode === true && els.demo) {
    els.demo.classList.remove(RESERVED_CLASS);
  }
}

/** True once /api/config says registration is open — the primary CTA then
 *  means "create an account" rather than "jump to the request-access form". */
export function primaryOpensRegister(config: PublicConfig | null): boolean {
  return config?.registration_enabled === true;
}

/** Collapse HTML source whitespace so an answer wrapped across three lines in
 *  the markup compares equal to the same sentence on one line in the JSON-LD. */
function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/**
 * Rewrite one answer inside the FAQPage JSON-LD, matched by its CURRENT text.
 *
 * Matching on the text rather than on the question's `name` is what keeps this
 * locale-agnostic: `/cs/` asks the same question in Czech, and a name match
 * would need a second lookup table that could drift from the markup. The two
 * copies of the answer are already required to be identical — the `<head>`
 * comment says the JSON-LD "mirrors the on-page FAQ verbatim", and
 * `landingHead.test.ts` now fails if they diverge — so the text IS the key.
 *
 * A parse failure or a miss leaves the block untouched, which is the same
 * fail-safe direction as the rest of this module: the structured data keeps
 * the (currently true) closed-registration answer.
 */
function rewriteFaqAnswer(script: HTMLScriptElement, closed: string, open: string): void {
  let data: unknown;
  try {
    data = JSON.parse(script.textContent ?? "") as unknown;
  } catch {
    return;
  }

  let replaced = false;
  const visit = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (typeof node !== "object" || node === null) return;
    const record = node as Record<string, unknown>;
    if (typeof record.text === "string" && normalizeText(record.text) === closed) {
      record.text = open;
      replaced = true;
      return;
    }
    Object.values(record).forEach(visit);
  };
  visit(data);

  if (replaced) script.textContent = JSON.stringify(data, null, 2);
}

/** The four places the page states the access model, plus the structured-data
 *  copy of the fourth. Every one is optional — a page that drops an id keeps
 *  its static wording rather than throwing. */
export interface RegistrationCopyElements {
  note: HTMLElement | null;
  faqAnswer: HTMLElement | null;
  accessHeading: HTMLElement | null;
  accessIntro: HTMLElement | null;
  faqSchema: HTMLScriptElement | null;
}

/**
 * Bring the rest of the page in line with the primary CTA once registration is
 * open. `applyConfig` above rewrites the BUTTON; without this, the button said
 * "Get started" on a page that still said "private alpha" in four other places
 * — the hero note, the visible FAQ answer, the Access heading and its intro —
 * one of which is mirrored into the FAQPage JSON-LD that Google has indexed.
 *
 * Deliberately a separate function from `applyConfig`, whose contract is that
 * it "only ever mutates the BUTTONS … so this can never shift layout". These
 * swaps replace prose in flow, so that promise does not extend to them. They
 * are still CLS-safe by construction: every swap is text-for-text inside an
 * element that already exists, nothing is hidden, added or removed, and the
 * replacement sentences are of comparable length. Nothing is swapped while
 * registration is closed — including on a failed or pending fetch, where the
 * static (closed) wording is both correct today and the safer thing to show.
 */
export function applyRegistrationCopy(
  config: PublicConfig | null,
  els: RegistrationCopyElements,
): void {
  if (config?.registration_enabled !== true) return;
  const copy = landingCopy();

  // Read the closed answer BEFORE overwriting it — it is the key the JSON-LD
  // block is matched on.
  const closedAnswer = normalizeText(els.faqAnswer?.textContent ?? "");

  if (els.note) els.note.textContent = copy.openCtaNote;
  if (els.faqAnswer) els.faqAnswer.textContent = copy.openFaqAvailability;
  if (els.accessHeading) els.accessHeading.textContent = copy.openAccessHeading;
  if (els.accessIntro) els.accessIntro.textContent = copy.openAccessIntro;
  if (els.faqSchema && closedAnswer) {
    rewriteFaqAnswer(els.faqSchema, closedAnswer, copy.openFaqAvailability);
  }
}

/**
 * Click handler for "Try the demo": start a session, then hand off to /app.
 *
 * Guarded against a second click because /auth/demo mints a BRAND-NEW
 * ephemeral account on every call — no idempotency, only a per-IP rate limit
 * — so a double-click creates two accounts racing to own one cookie.
 *
 * On failure it still navigates to /app rather than rendering an inline
 * error: the SPA's own Try Demo button lives there with proper error
 * reporting, and an inline message would push the page around under the
 * visitor's cursor (CLS).
 *
 * Extracted from the entry module so the guard is actually testable.
 */
export function createDemoHandler(
  button: HTMLElement,
  deps: { startDemo: () => Promise<unknown>; navigate: (url: string) => void; search: string },
): (event: Event) => void {
  let pending = false;
  return (event: Event) => {
    event.preventDefault();
    if (pending) return;
    pending = true;
    const original = button.textContent;
    button.textContent = landingCopy().ctaDemoStarting;
    void deps
      .startDemo()
      .then(() => deps.navigate(`/app${deps.search}`))
      .catch(() => {
        button.textContent = original;
        deps.navigate(`/app${deps.search}`);
      });
  };
}

