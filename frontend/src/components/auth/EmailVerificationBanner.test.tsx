import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { EmailVerificationBanner } from "./EmailVerificationBanner";
import * as AuthCtx from "../../contexts/AuthContext";
import type { AuthState } from "../../types";

/** Baseline: a logged-in, UNVERIFIED user — the only state that renders. */
function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    email: "u@example.com",
    emailVerified: false,
    resendVerification: vi.fn().mockResolvedValue(undefined),
    isDemo: false,
    isAdmin: false,
    ...over,
  } as unknown as AuthState;
}

beforeEach(() => vi.restoreAllMocks());

describe("EmailVerificationBanner", () => {
  it("prompts an unverified user and explains what's blocked", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({}));
    renderWithProviders(<EmailVerificationBanner />);
    expect(screen.getByText(/confirm your email address/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resend link/i })).toBeInTheDocument();
  });

  it("renders NOTHING for a verified user", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ emailVerified: true }));
    const { container } = renderWithProviders(<EmailVerificationBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders NOTHING when logged out", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ userId: null }));
    const { container } = renderWithProviders(<EmailVerificationBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("resends and confirms, without leaving a re-pressable button", async () => {
    // A disabled button would be misleading: the 60s server cooldown would
    // swallow an immediate second press anyway.
    const resend = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ resendVerification: resend }));

    const user = userEvent.setup();
    renderWithProviders(<EmailVerificationBanner />);
    await user.click(screen.getByRole("button", { name: /resend link/i }));

    await waitFor(() => expect(screen.getByText(/sent ✓/i)).toBeInTheDocument());
    expect(resend).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /resend link/i })).not.toBeInTheDocument();
  });

  it("keeps the button usable and explains a failed resend", async () => {
    const resend = vi.fn().mockRejectedValue(new Error("boom"));
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ resendVerification: resend }));

    const user = userEvent.setup();
    renderWithProviders(<EmailVerificationBanner />);
    await user.click(screen.getByRole("button", { name: /resend link/i }));

    await waitFor(() => expect(screen.getByText(/couldn't resend/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /resend link/i })).toBeEnabled();
  });

  it("uses an explicit background AND colour so it can't go dark-on-dark", () => {
    // The recurring white-on-white trap (.claude/rules/frontend.md): a surface
    // that sets one but not the other inherits the adaptive default.
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({}));
    renderWithProviders(<EmailVerificationBanner />);
    const banner = screen.getByRole("status");
    expect(banner.style.backgroundColor).toBeTruthy();
    expect(banner.style.color).toBeTruthy();
  });
});

describe("EmailVerificationBanner — the wrong-address escape hatch", () => {
  it("names the address the link was sent to", () => {
    // Without this a user who mistyped it has no way to notice: "check your
    // inbox" reads as advice to wait longer, not as a wrong address.
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ email: "typo@exmaple.com" }));
    renderWithProviders(<EmailVerificationBanner />);
    expect(screen.getByText("typo@exmaple.com")).toBeInTheDocument();
  });

  it("opens the change-address modal", async () => {
    // Resending only ever re-mails the SAME address, so without this a typo at
    // sign-up is unrecoverable — the whole point of the control.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<EmailVerificationBanner />);
    await user.click(screen.getByRole("button", { name: /wrong address/i }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /change email address/i })).toBeInTheDocument(),
    );
  });
});

describe("EmailVerificationBanner — accessibility of the dialog mount", () => {
  it("mounts the modal OUTSIDE the role=status live region", async () => {
    // role="status" is an ARIA live region. A dialog nested inside it gets
    // announced as a status update, so a screen reader reads the whole form out
    // as a notification and fights the dialog's own announcement.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    const { container } = renderWithProviders(<EmailVerificationBanner />);
    await user.click(screen.getByRole("button", { name: /wrong address/i }));

    const liveRegion = container.querySelector('[role="status"]');
    expect(liveRegion).not.toBeNull();
    const heading = screen.getByRole("heading", { name: /change email address/i });
    expect(liveRegion!.contains(heading)).toBe(false);
  });
});
