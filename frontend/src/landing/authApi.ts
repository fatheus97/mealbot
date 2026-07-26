// Auth calls for the static marketing landing (`/`).
//
// The landing authenticates directly rather than bouncing the visitor to the
// SPA's login form: /auth/login, /users/register and /auth/demo are all
// CSRF-exempt (see backend app/core/csrf.py — they bootstrap the CSRF cookie
// rather than requiring it), so a plain same-origin fetch is sufficient and
// this file needs neither api.ts's authFetch nor React.
//
// On success we persist the localStorage render hints and the caller hands off
// to /app, where AuthContext boots straight into the authenticated UI. The
// HttpOnly cookie set by these endpoints is the actual session; the hints only
// stop /app flashing logged-out (and — see auth/sessionHints.ts — are what
// makes AuthContext reconcile with the server at all).

import { storeSessionHints, type SessionProfile } from "../auth/sessionHints";
import { getStoredAttribution } from "../utils/attribution";

const API_BASE = "/api";

/** Message safe to show the visitor. Deliberately neutral for register so we
 *  never disclose whether an address already has an account. */
export class LandingAuthError extends Error {}

const LOGIN_FAILED = "Login failed. Check your credentials.";
const REGISTER_FAILED =
  "Registration failed. Please try again or contact info@trymealbot.com.";
const DEMO_FAILED = "Could not start the demo. Please try again.";
/** The account exists but the follow-up sign-in didn't land — telling the user
 *  "registration failed" would send them back to a 409 on the duplicate email.
 *  Mirrors AuthBar's AutoLoginAfterRegisterError copy. */
const REGISTERED_BUT_NOT_SIGNED_IN = "Account created — please sign in to continue.";

// Mirrors backend/app/models/user_schemas.py (Field min/max +
// validate_password_complexity). Duplicated deliberately — the server stays
// the authority, this only spares the visitor a round-trip to learn their
// password is too short. Keep in sync if the backend rule changes; the 422
// passthrough below is the safety net if they ever drift.
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;

/** Human-readable reason `password` fails the shared complexity rule, or null. */
export function passwordComplaint(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return `Password must be at most ${MAX_PASSWORD_LENGTH} characters.`;
  }
  if (!/[A-Z]/.test(password)) return "Password must contain an uppercase letter.";
  if (!/[a-z]/.test(password)) return "Password must contain a lowercase letter.";
  if (!/\d/.test(password)) return "Password must contain a digit.";
  return null;
}

/**
 * Pull a displayable message out of a FastAPI 422 body.
 *
 * ONLY called for 422 — that status is Pydantic rejecting the shape of what
 * the visitor just typed (password complexity, email format), so echoing it
 * is helpful and discloses nothing. Every other failure keeps the neutral
 * copy: a 409 on a duplicate email must NOT confirm that the address is
 * already registered.
 */
export function validationMessage(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const detail = (body as { detail?: unknown }).detail;
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const first = detail[0] as { msg?: unknown };
  if (typeof first?.msg !== "string") return null;
  // Pydantic prefixes custom ValueErrors with "Value error, ".
  const msg = first.msg.replace(/^Value error,\s*/i, "").trim();
  if (!msg) return null;
  return msg.endsWith(".") ? msg : `${msg}.`;
}

async function postJson(path: string, body?: unknown): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    // Same-origin, but explicit: the whole point is the Set-Cookie response.
    credentials: "include",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Narrow an untyped JSON body to something we can store hints from. */
function asProfile(data: unknown): SessionProfile | null {
  if (typeof data !== "object" || data === null) return null;
  const p = data as Record<string, unknown>;
  if (typeof p.id !== "number" || typeof p.email !== "string") return null;
  return p as unknown as SessionProfile;
}

async function readProfile(resp: Response, failureMessage: string): Promise<SessionProfile> {
  let parsed: unknown = null;
  try {
    parsed = await resp.json();
  } catch {
    throw new LandingAuthError(failureMessage);
  }
  const profile = asProfile(parsed);
  if (!profile) throw new LandingAuthError(failureMessage);
  return profile;
}

/** Persist hints then report where to go. Kept separate from navigation so the
 *  caller (and tests) control the redirect. */
function completeSession(profile: SessionProfile): SessionProfile {
  storeSessionHints(profile, Boolean(profile.is_demo));
  return profile;
}

export async function landingLogin(email: string, password: string): Promise<SessionProfile> {
  let resp: Response;
  try {
    resp = await postJson("/auth/login", { email, password });
  } catch {
    throw new LandingAuthError(LOGIN_FAILED);
  }
  if (!resp.ok) throw new LandingAuthError(LOGIN_FAILED);
  return completeSession(await readProfile(resp, LOGIN_FAILED));
}

/**
 * Register, then sign in — /users/register returns a plain message, not a
 * session, so the second call is what actually authenticates (same two-step
 * AuthContext.register performs).
 *
 * Replays first-touch attribution so a signup that happens entirely on the
 * landing page is still traceable to its campaign. captureAttribution() runs
 * on landing load (see main.ts); without that, a visitor who never reaches
 * /app before registering would lose their UTM data completely.
 */
export async function landingRegister(email: string, password: string): Promise<SessionProfile> {
  let resp: Response;
  try {
    resp = await postJson("/users/register", {
      email,
      password,
      ...getStoredAttribution(),
    });
  } catch {
    throw new LandingAuthError(REGISTER_FAILED);
  }
  if (!resp.ok) {
    // 422 = Pydantic rejected what they typed; echo the specific reason so
    // "must contain a digit" doesn't surface as a useless generic failure.
    // 403 (registration closed) / 409 (duplicate) / 5xx stay neutral.
    if (resp.status === 422) {
      const specific = await resp
        .json()
        .then(validationMessage)
        .catch(() => null);
      if (specific) throw new LandingAuthError(specific);
    }
    throw new LandingAuthError(REGISTER_FAILED);
  }

  try {
    return await landingLogin(email, password);
  } catch {
    throw new LandingAuthError(REGISTERED_BUT_NOT_SIGNED_IN);
  }
}

export async function landingDemo(): Promise<SessionProfile> {
  let resp: Response;
  try {
    resp = await postJson("/auth/demo");
  } catch {
    throw new LandingAuthError(DEMO_FAILED);
  }
  if (!resp.ok) throw new LandingAuthError(DEMO_FAILED);
  return completeSession(await readProfile(resp, DEMO_FAILED));
}
