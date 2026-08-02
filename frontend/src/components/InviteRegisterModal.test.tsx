import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { InviteRegisterModal } from "./InviteRegisterModal";
import * as api from "../api";

// InviteRegisterModal reads registerViaInvite off the real AuthContext, which
// calls authFetch("/config") on mount and authFetch("/auth/login") during the
// auto-login leg. Bare mocks here; the default behaviour is (re)installed in
// beforeEach so a per-test override (e.g. a failing /auth/login) can't leak into
// later tests (vi.clearAllMocks clears calls, not implementations).
vi.mock("../api", () => ({
  authFetch: vi.fn(),
  redeemInvite: vi.fn(),
}));

// A valid login profile, and an inert (ok:false) response — cast to Response
// since the mocks only touch .ok / .json.
const LOGIN_OK = {
  ok: true,
  json: () => Promise.resolve({ id: 5, email: "beta@example.com", is_admin: false }),
} as unknown as Response;
const INERT = { ok: false, json: () => Promise.resolve(null) } as unknown as Response;

function setUrl(search: string) {
  window.history.replaceState(null, "", `/${search}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  setUrl("");
  // Default: /auth/login succeeds, everything else (incl. /config) is inert.
  vi.mocked(api.authFetch).mockImplementation((path: string) =>
    Promise.resolve(typeof path === "string" && path.includes("/auth/login") ? LOGIN_OK : INERT),
  );
  vi.mocked(api.redeemInvite).mockResolvedValue(undefined);
});
afterEach(() => setUrl(""));

describe("InviteRegisterModal", () => {
  it("renders nothing without an invite param", () => {
    renderWithProviders(<InviteRegisterModal />);
    expect(
      screen.queryByRole("heading", { name: /create your account/i }),
    ).not.toBeInTheDocument();
  });

  it("opens on ?invite and strips the token from the URL immediately", async () => {
    setUrl("?invite=secret-tok&keep=1");
    renderWithProviders(<InviteRegisterModal />);

    expect(screen.getByRole("heading", { name: /create your account/i })).toBeInTheDocument();
    // The single-use secret must not linger in the address bar / history.
    await waitFor(() => expect(window.location.search).not.toContain("invite"));
    expect(window.location.search).toContain("keep=1");
  });

  it("redeems the invite and closes on success", async () => {
    setUrl("?invite=tok-xyz");
    const user = userEvent.setup();
    renderWithProviders(<InviteRegisterModal />);

    await user.type(screen.getByPlaceholderText("Email"), "beta@example.com");
    await user.type(screen.getByPlaceholderText("Password"), "BetaPass123");
    await user.type(screen.getByPlaceholderText("Confirm password"), "BetaPass123");
    // Consent gates the submit button, so tick it first.
    await user.click(screen.getByRole("checkbox", { name: /i accept the/i }));
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() =>
      expect(api.redeemInvite).toHaveBeenCalledWith("tok-xyz", "beta@example.com", "BetaPass123", true),
    );
    // Auto-logged-in → the modal closes.
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: /create your account/i }),
      ).not.toBeInTheDocument(),
    );
  });

  it("gates submit on password complexity and confirmation match", async () => {
    setUrl("?invite=tok");
    const user = userEvent.setup();
    renderWithProviders(<InviteRegisterModal />);

    await user.type(screen.getByPlaceholderText("Email"), "a@b.com");
    const submit = screen.getByRole("button", { name: /create account/i });

    await user.type(screen.getByPlaceholderText("Password"), "short");
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await user.clear(screen.getByPlaceholderText("Password"));
    await user.type(screen.getByPlaceholderText("Password"), "ValidPass123");
    await user.type(screen.getByPlaceholderText("Confirm password"), "Nope123456");
    expect(screen.getByText(/don't match/i)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    expect(api.redeemInvite).not.toHaveBeenCalled();
  });

  it("surfaces a friendly error for an invalid/expired link and stays on the form", async () => {
    setUrl("?invite=stale");
    vi.mocked(api.redeemInvite).mockRejectedValueOnce(
      new Error("This invite link is invalid or has expired."),
    );
    const user = userEvent.setup();
    renderWithProviders(<InviteRegisterModal />);

    await user.type(screen.getByPlaceholderText("Email"), "x@y.com");
    await user.type(screen.getByPlaceholderText("Password"), "ValidPass123");
    await user.type(screen.getByPlaceholderText("Confirm password"), "ValidPass123");
    // Consent gates the submit button, so tick it first.
    await user.click(screen.getByRole("checkbox", { name: /i accept the/i }));
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid or has expired/i);
    expect(screen.getByRole("heading", { name: /create your account/i })).toBeInTheDocument();
  });

  it("shows the sign-in prompt when the account is created but auto-login fails", async () => {
    setUrl("?invite=tok-si");
    // redeem succeeds, but every authFetch (incl. /auth/login) is inert → login()
    // throws → registerViaInvite wraps it as AutoLoginAfterRegisterError.
    vi.mocked(api.authFetch).mockResolvedValue(INERT);
    const user = userEvent.setup();
    renderWithProviders(<InviteRegisterModal />);

    await user.type(screen.getByPlaceholderText("Email"), "beta@example.com");
    await user.type(screen.getByPlaceholderText("Password"), "BetaPass123");
    await user.type(screen.getByPlaceholderText("Confirm password"), "BetaPass123");
    // Consent gates the submit button, so tick it first.
    await user.click(screen.getByRole("checkbox", { name: /i accept the/i }));
    await user.click(screen.getByRole("button", { name: /create account/i }));

    // The distinct "account created, just sign in" panel — NOT a red error — so the
    // invitee doesn't retry and hit a 409 on their now-taken email.
    expect(await screen.findByText(/couldn't sign you in automatically/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.redeemInvite).toHaveBeenCalledWith("tok-si", "beta@example.com", "BetaPass123", true);
  });
});
