// Vite entry for the static marketing landing (`/`) — see index.html and
// docs/landing-page-plan.md. Thin DOM wiring only; logic lives in cta.ts so
// it's unit-testable without a real DOM.
import {
  applyConfig,
  forwardSearchOnAppLinks,
  loggedInRedirectTarget,
  paramForwardTarget,
  LOGGED_IN_HINT_KEY,
  type PublicConfig,
} from "./cta";

const search = window.location.search;

const forwardTarget = paramForwardTarget(search);
if (forwardTarget) {
  window.location.replace(forwardTarget);
} else {
  let hasUserIdHint = false;
  try {
    hasUserIdHint = !!window.localStorage.getItem(LOGGED_IN_HINT_KEY);
  } catch {
    // localStorage can throw (private mode / quota) — treat as "not logged in".
  }
  const loggedInTarget = loggedInRedirectTarget(hasUserIdHint, search);
  if (loggedInTarget) {
    window.location.replace(loggedInTarget);
  } else {
    const primary = document.getElementById("cta-primary") as HTMLAnchorElement | null;
    const login = document.getElementById("cta-login") as HTMLAnchorElement | null;
    const demo = document.getElementById("cta-demo") as HTMLAnchorElement | null;

    forwardSearchOnAppLinks({ login, demo }, search);

    fetch("/api/config")
      .then((r) => (r.ok ? (r.json() as Promise<PublicConfig>) : null))
      .then((config) => applyConfig(config, { primary, demo }, search))
      .catch(() => applyConfig(null, { primary, demo }, search));
  }
}
