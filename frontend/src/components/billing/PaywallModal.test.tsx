import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { untranslatedEnglishIn } from "../../test/i18nAssertions";
import { useLocaleStore, DEFAULT_LOCALE } from "../../store/useLocaleStore";
import { PaywallModal } from "./PaywallModal";

const { startCheckout, reset, billingState, authState } = vi.hoisted(() => ({
  startCheckout: vi.fn(),
  reset: vi.fn(),
  billingState: { checkoutPending: false },
  authState: { annualBillingAvailable: false },
}));

vi.mock("../../hooks/useBilling", () => ({
  useBilling: () => ({
    startCheckout,
    openPortal: vi.fn(),
    checkoutPending: billingState.checkoutPending,
    portalPending: false,
    error: null,
    reset,
  }),
}));

// PaywallModal now reads annualBillingAvailable from auth context; mock it so the
// tests control whether the plan toggle renders (no AuthProvider/api needed).
vi.mock("../../contexts/AuthContext", () => ({
  useAuth: () => authState,
}));

function firePaywall() {
  act(() => {
    window.dispatchEvent(new Event("mealbot:paywall"));
  });
}

describe("PaywallModal", () => {
  beforeEach(() => {
    startCheckout.mockClear();
    reset.mockClear();
    billingState.checkoutPending = false;
    authState.annualBillingAvailable = false;
  });

  it("is closed until the paywall event fires", () => {
    render(<PaywallModal />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    firePaywall();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/subscription required/i)).toBeInTheDocument();
  });

  it("starts checkout on the trial button (monthly by default)", async () => {
    render(<PaywallModal />);
    firePaywall();
    await userEvent.click(screen.getByRole("button", { name: /start free trial/i }));
    expect(startCheckout).toHaveBeenCalledTimes(1);
    expect(startCheckout).toHaveBeenCalledWith("monthly");
  });

  it("hides the plan toggle when annual is unavailable", () => {
    authState.annualBillingAvailable = false;
    render(<PaywallModal />);
    firePaywall();
    expect(screen.queryByRole("group", { name: /billing plan/i })).not.toBeInTheDocument();
  });

  it("shows the plan toggle and checks out the selected annual plan", async () => {
    authState.annualBillingAvailable = true;
    render(<PaywallModal />);
    firePaywall();
    const group = screen.getByRole("group", { name: /billing plan/i });
    expect(group).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /annual/i }));
    await userEvent.click(screen.getByRole("button", { name: /start free trial/i }));
    expect(startCheckout).toHaveBeenCalledWith("annual");
  });

  it("dismisses on 'Maybe later' without starting checkout", async () => {
    render(<PaywallModal />);
    firePaywall();
    await userEvent.click(screen.getByRole("button", { name: /maybe later/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(startCheckout).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog on open (a11y)", () => {
    render(<PaywallModal />);
    firePaywall();
    // Focus lands on the non-committal control, not the obscured page behind.
    expect(screen.getByRole("button", { name: /maybe later/i })).toHaveFocus();
  });

  it("clears any stale billing error when reopened", () => {
    render(<PaywallModal />);
    firePaywall();
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("pins focus to the dialog while checkout is pending (both buttons disabled)", () => {
    billingState.checkoutPending = true;
    render(<PaywallModal />);
    firePaywall();
    // With both controls disabled, focus must stay inside the dialog, not revert
    // to <body> and let Tab escape to the page behind the backdrop.
    expect(screen.getByRole("dialog")).toHaveFocus();
  });

  // The legal links are asserted in BOTH locales, because the bug was not a
  // missing translation — the markup was correct English and the hrefs were
  // correct for English. Only a Czech reader saw the wrong document, and no
  // English-locale test could ever have noticed.
  it("links English readers to the English contract", () => {
    render(<PaywallModal />);
    firePaywall();
    expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute(
      "href",
      "/terms",
    );
    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });

  describe("in Czech", () => {
    beforeEach(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    afterEach(() =>
      useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false }),
    );

    it("links to the CZECH contract, not the English one", () => {
      // #396 made the two editions equally authoritative, and the Czech one is
      // what binds a Czech consumer. Sending them to /terms one click from
      // paying pointed at the wrong binding document.
      render(<PaywallModal />);
      firePaywall();
      const links = screen.getAllByRole("link");
      expect(links.map((a) => a.getAttribute("href"))).toEqual([
        "/cs/terms",
        "/cs/privacy",
      ]);
    });

    it("renders no English, with the plan toggle shown", () => {
      authState.annualBillingAvailable = true;
      render(<PaywallModal />);
      firePaywall();
      expect(untranslatedEnglishIn(document.body)).toEqual([]);
    });

    it("writes the price with a decimal comma", () => {
      authState.annualBillingAvailable = true;
      render(<PaywallModal />);
      firePaywall();
      // "€4.99" is not a number a Czech reader parses as four euros ninety-nine.
      expect(screen.getByText("4,99 €")).toBeInTheDocument();
      expect(screen.queryByText(/€4\.99/)).not.toBeInTheDocument();
    });
  });
});
