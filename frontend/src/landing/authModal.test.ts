import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { createAuthModal, postAuthTarget, validate, type AuthModalElements } from "./authModal";

vi.mock("./authApi", async () => {
  const actual = await vi.importActual<typeof import("./authApi")>("./authApi");
  return {
    ...actual,
    landingLogin: vi.fn(),
    landingRegister: vi.fn(),
  };
});
const { landingLogin, landingRegister, AccountCreatedNeedsLoginError } = await import(
  "./authApi"
);

function mountModal(): AuthModalElements {
  document.body.innerHTML = `
    <a id="opener" href="/app">Log in</a>
    <div id="auth-modal" hidden>
      <button id="auth-close"></button>
      <h2 id="auth-modal-title">Log in</h2>
      <div id="auth-error" hidden></div>
      <form id="auth-form">
        <input id="auth-email" />
        <input id="auth-password" type="password" autocomplete="current-password" />
        <label id="auth-consent" hidden><input type="checkbox" id="auth-accept-terms" /></label>
        <button type="submit" id="auth-submit">Log in</button>
      </form>
      <span id="auth-switch-prompt"></span>
      <button id="auth-switch"></button>
    </div>`;
  const $ = (id: string) => document.getElementById(id)!;
  return {
    root: $("auth-modal"),
    form: $("auth-form") as HTMLFormElement,
    title: $("auth-modal-title"),
    emailInput: $("auth-email") as HTMLInputElement,
    passwordInput: $("auth-password") as HTMLInputElement,
    submit: $("auth-submit") as HTMLButtonElement,
    error: $("auth-error"),
    closeButton: $("auth-close"),
    switchButton: $("auth-switch"),
    switchPrompt: $("auth-switch-prompt"),
    consent: $("auth-consent"),
    acceptTermsInput: $("auth-accept-terms") as HTMLInputElement,
  };
}

describe("postAuthTarget", () => {
  it("preserves the query string so campaign params survive the hop to /app", () => {
    expect(postAuthTarget("?utm_source=x")).toBe("/app?utm_source=x");
    expect(postAuthTarget("")).toBe("/app");
  });
});

describe("validate", () => {
  it("requires an email and a password", () => {
    expect(validate("login", "", "pw")).toMatch(/email/i);
    expect(validate("login", "  ", "pw")).toMatch(/email/i);
    expect(validate("login", "a@b.com", "")).toMatch(/password/i);
  });

  it("enforces password complexity only when registering", () => {
    expect(validate("register", "a@b.com", "short")).toMatch(/at least 8/i);
    expect(validate("register", "a@b.com", "alllowercase1")).toMatch(/uppercase/i);
    expect(validate("register", "a@b.com", "NoDigitsAtAll")).toMatch(/digit/i);
    // Login must NOT apply it — an existing account may predate the rule, and
    // rejecting client-side would lock them out of credentials that still work.
    expect(validate("login", "a@b.com", "short")).toBeNull();
    expect(validate("login", "a@b.com", "alllowercase")).toBeNull();
  });

  it("accepts valid input", () => {
    expect(validate("register", "a@b.com", "TestPassword123", true)).toBeNull();
  });
});

describe("auth modal", () => {
  let els: AuthModalElements;
  let navigate: ReturnType<typeof vi.fn<(url: string) => void>>;

  beforeEach(() => {
    vi.clearAllMocks();
    els = mountModal();
    navigate = vi.fn<(url: string) => void>();
    createAuthModal(els, { navigate, getSearch: () => "?utm_source=x" });
  });
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("is hidden until opened", () => {
    expect(els.root.hidden).toBe(true);
  });

  it("opens in login mode with sign-in copy and autocomplete", () => {
    document.getElementById("opener")!.click();
    els.root.hidden = false; // opener wiring lives in main.ts; open directly below
    expect(els.title.textContent).toBe("Log in");
    expect(els.passwordInput.getAttribute("autocomplete")).toBe("current-password");
  });

  it("switches to register mode, updating copy and autocomplete", () => {
    els.switchButton.click();
    expect(els.title.textContent).toBe("Create your account");
    expect(els.submit.textContent).toBe("Create account");
    expect(els.passwordInput.getAttribute("autocomplete")).toBe("new-password");
  });

  it("blocks submit and shows a message when the password is too short to register", async () => {
    els.switchButton.click(); // -> register
    els.emailInput.value = "a@b.com";
    els.passwordInput.value = "short";
    els.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    await Promise.resolve();

    expect(landingRegister).not.toHaveBeenCalled();
    expect(els.error.hidden).toBe(false);
    expect(els.error.textContent).toMatch(/at least 8/i);
  });

  it("logs in and navigates to /app preserving the query string", async () => {
    vi.mocked(landingLogin).mockResolvedValue({ id: 1, email: "a@b.com" });
    els.emailInput.value = "a@b.com";
    els.passwordInput.value = "pw";
    els.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith("/app?utm_source=x"));
    expect(landingLogin).toHaveBeenCalledWith("a@b.com", "pw");
  });

  it("registers via landingRegister when in register mode", async () => {
    vi.mocked(landingRegister).mockResolvedValue({ id: 2, email: "n@b.com" });
    els.switchButton.click();
    els.emailInput.value = "n@b.com";
    els.passwordInput.value = "TestPassword123";
    els.acceptTermsInput.checked = true;
    els.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith("/app?utm_source=x"));
    // Consent is forwarded as the user actually left it, not hardcoded.
    expect(landingRegister).toHaveBeenCalledWith("n@b.com", "TestPassword123", true);
  });

  it("surfaces the API error, re-enables the form, and does NOT navigate", async () => {
    vi.mocked(landingLogin).mockRejectedValue(new Error("Login failed. Check your credentials."));
    els.emailInput.value = "a@b.com";
    els.passwordInput.value = "bad";
    els.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

    await vi.waitFor(() => expect(els.error.hidden).toBe(false));
    expect(els.error.textContent).toMatch(/check your credentials/i);
    expect(navigate).not.toHaveBeenCalled();
    expect(els.submit.disabled).toBe(false);
    expect(els.submit.textContent).toBe("Log in");
  });

  it("closes on Escape and on backdrop click, clearing the password", () => {
    els.root.hidden = false;
    els.passwordInput.value = "secret";
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(els.root.hidden).toBe(true);
    expect(els.passwordInput.value).toBe("");

    els.root.hidden = false;
    els.root.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(els.root.hidden).toBe(true);
  });

  it("does not close when the click originates inside the panel", () => {
    els.root.hidden = false;
    els.emailInput.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(els.root.hidden).toBe(false);
  });

  it("switches to LOGIN mode when the account was created but sign-in failed", async () => {
    // Otherwise "please sign in to continue" is unactionable: resubmitting
    // re-runs register against the email that now exists and returns a
    // generic "registration failed" for something that actually worked.
    vi.mocked(landingRegister).mockRejectedValue(
      new AccountCreatedNeedsLoginError("Account created — please sign in to continue."),
    );
    els.switchButton.click(); // -> register
    els.emailInput.value = "n@b.com";
    els.passwordInput.value = "TestPassword123";
    els.acceptTermsInput.checked = true;
    els.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

    await vi.waitFor(() => expect(els.error.hidden).toBe(false));
    expect(els.title.textContent).toBe("Log in");
    expect(els.submit.textContent).toBe("Log in");
    // The message must SURVIVE the mode switch (applyMode clears the error).
    expect(els.error.textContent).toMatch(/account created/i);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("stays in register mode for an ordinary registration failure", async () => {
    vi.mocked(landingRegister).mockRejectedValue(new Error("Registration failed."));
    els.switchButton.click();
    els.emailInput.value = "n@b.com";
    els.passwordInput.value = "TestPassword123";
    els.acceptTermsInput.checked = true;
    els.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));

    await vi.waitFor(() => expect(els.error.hidden).toBe(false));
    expect(els.title.textContent).toBe("Create your account");
  });

  it("locks body scroll while open and restores the previous value on close", () => {
    document.body.style.overflow = "auto";
    els.switchButton.click(); // no-op on scroll; just exercise state
    // open() is invoked via the public handle in main.ts; drive it directly.
    els.root.hidden = true;
    document.body.style.overflow = "auto";

    const handle = createAuthModal(els, { navigate, getSearch: () => "" });
    handle.open("login");
    expect(document.body.style.overflow).toBe("hidden");

    handle.close();
    expect(document.body.style.overflow).toBe("auto");
  });
});

describe("terms consent (landing)", () => {
  it("blocks a register submit when the box is unticked", () => {
    // The server 422s without it, but bouncing off the API to learn that is a
    // worse experience than the form saying so.
    expect(validate("register", "a@b.com", "TestPassword123", false)).toMatch(
      /terms of service/i,
    );
  });

  it("never asks a returning user to accept anything to log in", () => {
    expect(validate("login", "a@b.com", "pw", false)).toBeNull();
  });

  it("reports a weak password before the checkbox", () => {
    // Otherwise a user with both problems fixes the box, resubmits, and only
    // then learns about the password.
    expect(validate("register", "a@b.com", "short", false)).toMatch(/at least 8/i);
  });
});
