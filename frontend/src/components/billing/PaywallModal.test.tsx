import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PaywallModal } from "./PaywallModal";

const { startCheckout, reset, billingState } = vi.hoisted(() => ({
  startCheckout: vi.fn(),
  reset: vi.fn(),
  billingState: { checkoutPending: false },
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
  });

  it("is closed until the paywall event fires", () => {
    render(<PaywallModal />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    firePaywall();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/subscription required/i)).toBeInTheDocument();
  });

  it("starts checkout on the trial button", async () => {
    render(<PaywallModal />);
    firePaywall();
    await userEvent.click(screen.getByRole("button", { name: /start free trial/i }));
    expect(startCheckout).toHaveBeenCalledTimes(1);
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
});
