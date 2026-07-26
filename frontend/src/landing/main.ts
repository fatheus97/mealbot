// Vite entry for the static marketing landing (`/`) — see index.html and
// docs/landing-page-plan.md. Thin DOM wiring only; the logic lives in cta.ts /
// authApi.ts / authModal.ts so it's unit-testable without a real DOM.
//
// PROGRESSIVE ENHANCEMENT CONTRACT: every CTA is a real <a href="/app"> in the
// static HTML and works with JS disabled (landing on the SPA's own AuthBar).
// Everything below only *intercepts* those clicks to offer the nicer in-page
// flow — it never creates the only path to a feature.
import {
  applyConfig,
  createDemoHandler,
  forwardSearchOnAppLinks,
  loggedInRedirectTarget,
  paramForwardTarget,
  primaryOpensRegister,
  LOGGED_IN_HINT_KEY,
  type PublicConfig,
} from "./cta";
import { createAuthModal, type AuthModalElements } from "./authModal";
import { landingDemo } from "./authApi";
import { captureAttribution } from "../utils/attribution";

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
    // First-touch attribution must be captured HERE, not just in the SPA.
    // AuthContext calls this on /app, but a visitor who registers straight
    // from the landing modal never loads /app beforehand — without this their
    // ?utm_* data would be lost before the signup that it's meant to explain.
    captureAttribution();

    const primary = document.getElementById("cta-primary") as HTMLAnchorElement | null;
    const login = document.getElementById("cta-login") as HTMLAnchorElement | null;
    const demo = document.getElementById("cta-demo") as HTMLAnchorElement | null;

    forwardSearchOnAppLinks({ login, demo }, search);

    const modalRoot = document.getElementById("auth-modal");
    const modal = modalRoot
      ? createAuthModal(
          {
            root: modalRoot,
            form: document.getElementById("auth-form") as HTMLFormElement,
            title: document.getElementById("auth-modal-title") as HTMLElement,
            emailInput: document.getElementById("auth-email") as HTMLInputElement,
            passwordInput: document.getElementById("auth-password") as HTMLInputElement,
            submit: document.getElementById("auth-submit") as HTMLButtonElement,
            error: document.getElementById("auth-error") as HTMLElement,
            closeButton: document.getElementById("auth-close") as HTMLElement,
            switchButton: document.getElementById("auth-switch") as HTMLElement,
            switchPrompt: document.getElementById("auth-switch-prompt") as HTMLElement,
          } satisfies AuthModalElements,
          { navigate: (url) => window.location.assign(url), getSearch: () => search },
        )
      : null;

    if (modal && login) {
      login.addEventListener("click", (e) => {
        e.preventDefault();
        modal.open("login");
      });
    }

    if (demo) {
      demo.addEventListener(
        "click",
        createDemoHandler(demo, {
          startDemo: landingDemo,
          navigate: (url) => window.location.assign(url),
          search,
        }),
      );
    }

    fetch("/api/config")
      .then((r) => (r.ok ? (r.json() as Promise<PublicConfig>) : null))
      .then((config) => {
        applyConfig(config, { primary, demo }, search);
        // Only once registration is actually open does the primary CTA mean
        // "sign up" — while it's closed it stays the mailto request-access
        // link, which must NOT be hijacked into a register form that would 403.
        if (modal && primary && primaryOpensRegister(config)) {
          primary.addEventListener("click", (e) => {
            e.preventDefault();
            modal.open("register");
          });
        }
      })
      .catch(() => applyConfig(null, { primary, demo }, search));
  }
}
