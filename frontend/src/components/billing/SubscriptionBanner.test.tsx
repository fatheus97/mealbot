import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SubscriptionBanner } from "./SubscriptionBanner";
import { untranslatedEnglishIn } from "../../test/i18nAssertions";
import { useLocaleStore, DEFAULT_LOCALE } from "../../store/useLocaleStore";

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
    cancelAtPeriodEnd: false,
    isSubscribed: false,
    isComped: false,
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

  it("renders nothing for a comped user even with a stray subscription status", () => {
    // Comped access shouldn't show billing UI — not even a false past_due warning.
    mockedUseAuth.mockReturnValue(
      authState({ isComped: true, isSubscribed: true, subscriptionStatus: "past_due" }),
    );
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

  it("says 'ends' (not 'renews') when canceled at period end", () => {
    mockedUseAuth.mockReturnValue(
      authState({
        isSubscribed: true,
        subscriptionStatus: "trialing",
        cancelAtPeriodEnd: true,
        currentPeriodEnd: "2026-07-28T00:00:00Z",
      }),
    );
    render(<SubscriptionBanner />);
    expect(screen.getByText(/canceled/i)).toBeInTheDocument();
    expect(screen.getByText(/ends/i)).toBeInTheDocument();
    expect(screen.queryByText(/renews/i)).not.toBeInTheDocument();
  });

  it("says 'canceled — ends' (not 'update your card') when past_due AND canceled", () => {
    mockedUseAuth.mockReturnValue(
      authState({
        isSubscribed: true,
        subscriptionStatus: "past_due",
        cancelAtPeriodEnd: true,
        currentPeriodEnd: "2026-07-28T00:00:00Z",
      }),
    );
    render(<SubscriptionBanner />);
    expect(screen.getByText(/canceled/i)).toBeInTheDocument();
    expect(screen.getByText(/ends/i)).toBeInTheDocument();
    expect(screen.queryByText(/update your card/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /manage/i })).toBeInTheDocument();
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

  describe("in Czech", () => {
    beforeEach(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    afterEach(() =>
      useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false }),
    );

    // One case per branch of the message selector. The branches ARE the change
    // — they replaced a stem plus a shared "— renews {date}" suffix — so a
    // single smoke render would leave five of the six unproven.
    it.each([
      ["trialing", { subscriptionStatus: "trialing", isSubscribed: true }],
      ["active", { subscriptionStatus: "active", isSubscribed: true }],
      ["past_due", { subscriptionStatus: "past_due", isSubscribed: true }],
      ["subscribe", { subscriptionStatus: "canceled", isSubscribed: false }],
      [
        "trial canceled",
        { subscriptionStatus: "trialing", isSubscribed: true, cancelAtPeriodEnd: true },
      ],
      [
        "subscription canceled",
        { subscriptionStatus: "active", isSubscribed: true, cancelAtPeriodEnd: true },
      ],
    ])("renders no English in the %s state", (_label, overrides) => {
      mockedUseAuth.mockReturnValue(
        authState({ currentPeriodEnd: "2026-09-01T00:00:00Z", ...overrides }),
      );
      const { container } = render(<SubscriptionBanner />);
      expect(untranslatedEnglishIn(container)).toEqual([]);
    });

    it("formats the renewal date in Czech, not the browser's locale", () => {
      // jsdom reports navigator.language as en-US, so the old
      // `toLocaleDateString(undefined, …)` rendered "Sep 1, 2026" right here.
      // That is the bug; this asserts it is gone.
      mockedUseAuth.mockReturnValue(
        authState({
          subscriptionStatus: "active",
          isSubscribed: true,
          currentPeriodEnd: "2026-09-01T00:00:00Z",
        }),
      );
      render(<SubscriptionBanner />);
      expect(screen.getByRole("status").textContent).not.toMatch(/Sep/);
    });

    it("uses a separate sentence when there is no date, not an empty hole", () => {
      // Dated and undated are different keys precisely so a null period end
      // cannot leave a dangling ", obnovuje se ." behind.
      mockedUseAuth.mockReturnValue(
        authState({ subscriptionStatus: "active", isSubscribed: true, currentPeriodEnd: null }),
      );
      render(<SubscriptionBanner />);
      const text = screen.getByRole("status").textContent ?? "";
      expect(text).not.toMatch(/\s\.|,\s*\.|,\s*$/);
    });
  });
});
