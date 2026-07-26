import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../../test/test-utils";
import { VerifyEmailHandler } from "./VerifyEmailHandler";
import * as AuthCtx from "../../contexts/AuthContext";
import * as api from "../../api";
import type { AuthState } from "../../types";

function mockAuth(over: Partial<AuthState> = {}) {
  vi.spyOn(AuthCtx, "useAuth").mockReturnValue({
    userId: 1,
    refreshProfile: vi.fn().mockResolvedValue(undefined),
    ...over,
  } as unknown as AuthState);
}

function setUrl(search: string) {
  window.history.replaceState(null, "", `/app${search}`);
}

beforeEach(() => {
  vi.restoreAllMocks();
  setUrl("");
});
afterEach(() => setUrl(""));

describe("VerifyEmailHandler", () => {
  it("renders nothing when there is no verify_token", () => {
    mockAuth();
    const spy = vi.spyOn(api, "verifyEmail");
    const { container } = renderWithProviders(<VerifyEmailHandler />);
    expect(container).toBeEmptyDOMElement();
    expect(spy).not.toHaveBeenCalled();
  });

  it("redeems the token, confirms, and STRIPS it from the URL", async () => {
    // Stripping matters: the token is single-use, so a reload would otherwise
    // replay it and show a failure for a confirmation that worked — and it
    // would linger in history.
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc123");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    expect(api.verifyEmail).toHaveBeenCalledWith("abc123");
    expect(window.location.search).not.toContain("verify_token");
  });

  it("preserves other query params while stripping the token", async () => {
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc&utm_source=news");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    expect(window.location.search).toContain("utm_source=news");
    expect(window.location.search).not.toContain("verify_token");
  });

  it("refreshes the profile on success so the banner disappears immediately", async () => {
    const refreshProfile = vi.fn().mockResolvedValue(undefined);
    mockAuth({ refreshProfile });
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(refreshProfile).toHaveBeenCalled());
  });

  it("works logged-OUT (the link often opens in a different browser)", async () => {
    const refreshProfile = vi.fn();
    mockAuth({ userId: null, refreshProfile });
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    // Nothing to refresh when no one is signed in here.
    expect(refreshProfile).not.toHaveBeenCalled();
  });

  it("points a failed redemption at the resend affordance", async () => {
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("expired"));
    setUrl("?verify_token=stale");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() =>
      expect(screen.getByText(/invalid or has expired/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/resend link/i)).toBeInTheDocument();
  });

  it("redeems ONCE even though StrictMode double-invokes effects", async () => {
    // The token is single-use: a second redeem would fail and show an error
    // for a confirmation that actually succeeded.
    mockAuth();
    const spy = vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    const { rerender } = renderWithProviders(<VerifyEmailHandler />);
    rerender(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
