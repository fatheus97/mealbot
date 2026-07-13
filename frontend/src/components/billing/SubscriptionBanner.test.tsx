import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SubscriptionBanner } from "./SubscriptionBanner";

const { startCheckout, openPortal } = vi.hoisted(() => ({
  startCheckout: vi.fn(),
  openPortal: vi.fn(),
}));

vi.mock("../../hooks/useBilling", () => ({
  useBilling: () => ({
    startCheckout,
    openPortal,
    checkoutPending: false,
    portalPending: false,
    error: null,
  }),
}));

vi.mock("../../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
import { useAuth } from "../../contexts/AuthContext";
const mockedUseAuth = useAuth as unknown as ReturnType<typeof vi.fn>;

function authState(overrides: Record<string, unknown> = {}) {
  return {
    isDemo: false,
    subscriptionStatus: "none",
    currentPeriodEnd: null,
    isSubscribed: false,
    ...overrides,
  };
}

describe("SubscriptionBanner", () => {
  beforeEach(() => {
    startCheckout.mockClear();
    openPortal.mockClear();
  });

  it("renders nothing for a demo account", () => {
    mockedUseAuth.mockReturnValue(authState({ isDemo: true, isSubscribed: false }));
    const { container } = render(<SubscriptionBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when entitled with status none (billing off / bypass)", () => {
    mockedUseAuth.mockReturnValue(authState({ isSubscribed: true, subscriptionStatus: "none" }));
    const { container } = render(<SubscriptionBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the trial banner and Manage → portal", async () => {
    mockedUseAuth.mockReturnValue(
      authState({ isSubscribed: true, subscriptionStatus: "trialing", currentPeriodEnd: "2026-08-01T00:00:00Z" }),
    );
    render(<SubscriptionBanner />);
    expect(screen.getByText(/free trial/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /manage/i }));
    expect(openPortal).toHaveBeenCalledTimes(1);
    expect(startCheckout).not.toHaveBeenCalled();
  });

  it("shows the past_due warning and Update payment → portal", async () => {
    mockedUseAuth.mockReturnValue(authState({ isSubscribed: true, subscriptionStatus: "past_due" }));
    render(<SubscriptionBanner />);
    expect(screen.getByText(/payment failed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /update payment/i }));
    expect(openPortal).toHaveBeenCalledTimes(1);
  });

  it("shows a subtle active banner and Manage → portal", async () => {
    mockedUseAuth.mockReturnValue(authState({ isSubscribed: true, subscriptionStatus: "active" }));
    render(<SubscriptionBanner />);
    expect(screen.getByText(/subscribed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /manage/i }));
    expect(openPortal).toHaveBeenCalledTimes(1);
  });

  it("shows the Subscribe CTA when not entitled → checkout", async () => {
    mockedUseAuth.mockReturnValue(authState({ isSubscribed: false, subscriptionStatus: "canceled" }));
    render(<SubscriptionBanner />);
    expect(screen.getByText(/subscribe to keep/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /subscribe/i }));
    expect(startCheckout).toHaveBeenCalledTimes(1);
    expect(openPortal).not.toHaveBeenCalled();
  });
});
