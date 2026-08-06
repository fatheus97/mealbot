// The landing page's login / register dialog.
//
// Vanilla DOM on purpose: this is the SEO-critical page, and mounting React
// just to render two inputs would take the landing bundle from ~1 kB to the
// SPA's ~450 kB and regress LCP on the one page where it matters most. The
// markup itself lives in index.html (static, styled alongside the rest of the
// page) — this module only wires behaviour to it.
//
// The dialog is position:fixed and therefore out of flow, so showing it can't
// shift the page behind it (the CLS rule in .claude/rules/frontend.md).

import {
  AccountCreatedNeedsLoginError,
  landingLogin,
  landingRegister,
  passwordComplaint,
} from "./authApi";
import { landingCopy } from "./copy";

export type AuthMode = "login" | "register";

export interface AuthModalElements {
  root: HTMLElement;
  form: HTMLFormElement;
  title: HTMLElement;
  emailInput: HTMLInputElement;
  passwordInput: HTMLInputElement;
  submit: HTMLButtonElement;
  error: HTMLElement;
  closeButton: HTMLElement;
  switchButton: HTMLElement;
  switchPrompt: HTMLElement;
  /** Consent row, revealed only in register mode. */
  consent: HTMLElement;
  acceptTermsInput: HTMLInputElement;
}

// Built per call rather than at module load: `landingCopy()` reads
// `document.documentElement.lang`, which does not exist yet when this module
// is first evaluated in a test that has not set up a DOM.
function modeCopy(): Record<AuthMode, { title: string; submit: string; prompt: string; switchTo: string }> {
  const c = landingCopy();
  return {
    login: {
      title: c.authLoginTitle,
      submit: c.authLoginSubmit,
      prompt: c.authLoginPrompt,
      switchTo: c.authLoginSwitchTo,
    },
    register: {
      title: c.authRegisterTitle,
      submit: c.authRegisterSubmit,
      prompt: c.authRegisterPrompt,
      switchTo: c.authRegisterSwitchTo,
    },
  };
}

/** Where to send the visitor once authenticated. Preserves the query string so
 *  campaign params survive the hop (same reasoning as the CTA links). */
export function postAuthTarget(search: string): string {
  return `/app${search}`;
}

/**
 * Client-side guard so a weak password surfaces instantly instead of after a
 * 422 round-trip. The backend remains the authority — this is purely about
 * feedback latency.
 *
 * Complexity is checked ONLY when registering. Applying it at login would
 * lock out any account whose password predates the current rule: they'd be
 * unable to submit the very credentials that still work.
 */
export function validate(
  mode: AuthMode,
  email: string,
  password: string,
  acceptTerms = false,
): string | null {
  const copy = landingCopy();
  if (!email.trim()) return copy.authNeedEmail;
  if (!password) return copy.authNeedPassword;
  if (mode !== "register") return null;
  const weak = passwordComplaint(password);
  if (weak) return weak;
  // Checked last so a user fixing their password is not also told about the
  // checkbox on every keystroke.
  if (!acceptTerms) {
    return copy.authNeedTerms;
  }
  return null;
}

export function createAuthModal(
  els: AuthModalElements,
  opts: { navigate: (url: string) => void; getSearch: () => string },
) {
  let mode: AuthMode = "login";
  let busy = false;
  // Restore focus to whatever opened the dialog, so keyboard users aren't
  // dumped at the top of the document on close.
  let lastFocused: HTMLElement | null = null;
  let previousBodyOverflow = "";

  function setError(message: string | null): void {
    els.error.textContent = message ?? "";
    els.error.hidden = !message;
  }

  function applyMode(next: AuthMode): void {
    mode = next;
    const copy = modeCopy()[next];
    els.title.textContent = copy.title;
    els.submit.textContent = copy.submit;
    els.switchPrompt.textContent = copy.prompt;
    els.switchButton.textContent = copy.switchTo;
    // Let password managers tell "sign in" from "create account".
    els.passwordInput.setAttribute(
      "autocomplete",
      next === "register" ? "new-password" : "current-password",
    );
    els.consent.hidden = next !== "register";
    // Cleared on the way out so switching register -> login -> register can
    // never present an already-ticked box the user did not tick this time.
    if (next !== "register") els.acceptTermsInput.checked = false;
    setError(null);
  }

  function open(next: AuthMode): void {
    lastFocused = document.activeElement as HTMLElement | null;
    applyMode(next);
    els.root.hidden = false;
    // Stop the page scrolling behind the backdrop (most visible on touch),
    // saving/restoring the previous value exactly as ModalShell does for the
    // SPA's own dialogs.
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    els.emailInput.focus();
  }

  function close(): void {
    if (busy) return; // don't abandon an in-flight request mid-submit
    els.root.hidden = true;
    els.passwordInput.value = "";
    els.acceptTermsInput.checked = false;
    setError(null);
    document.body.style.overflow = previousBodyOverflow;
    lastFocused?.focus();
  }

  function setBusy(next: boolean): void {
    busy = next;
    els.submit.disabled = next;
    const copy = landingCopy();
    els.submit.textContent = next
      ? mode === "register"
        ? copy.authBusyRegister
        : copy.authBusyLogin
      : modeCopy()[mode].submit;
  }

  async function submit(event: Event): Promise<void> {
    event.preventDefault();
    if (busy) return;
    const email = els.emailInput.value;
    const password = els.passwordInput.value;
    const acceptTerms = els.acceptTermsInput.checked;

    const invalid = validate(mode, email, password, acceptTerms);
    if (invalid) {
      setError(invalid);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await landingRegister(email, password, acceptTerms);
      } else {
        await landingLogin(email, password);
      }
      // Authenticated: hand off to the SPA. Deliberately leave the dialog open
      // and busy — the navigation is already underway, and re-enabling the
      // form would invite a double submit during the unload.
      opts.navigate(postAuthTarget(opts.getSearch()));
    } catch (err) {
      setBusy(false);
      const accountExists = err instanceof AccountCreatedNeedsLoginError;
      const message =
        err instanceof Error ? err.message : landingCopy().authGenericError;
      if (accountExists) {
        // The account was created — flip the form to login so "please sign in
        // to continue" is actionable. Without this, resubmitting re-runs
        // register against the email that now exists and returns a generic
        // "registration failed" for something that actually succeeded.
        // applyMode clears the error, so set it afterwards.
        applyMode("login");
      }
      setError(message);
      els.passwordInput.focus();
    }
  }

  els.form.addEventListener("submit", (e) => void submit(e));
  els.closeButton.addEventListener("click", close);
  els.switchButton.addEventListener("click", () => {
    applyMode(mode === "login" ? "register" : "login");
    els.emailInput.focus();
  });
  // Backdrop click closes; clicks inside the panel must not bubble out to it.
  els.root.addEventListener("click", (e) => {
    if (e.target === els.root) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.root.hidden) close();
  });

  return { open, close, getMode: () => mode };
}
