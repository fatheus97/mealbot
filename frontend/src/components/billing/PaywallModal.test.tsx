import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PaywallModal } from "./PaywallModal";

const { startCheckout, reset } = vi.hoisted(() => ({ startCheckout: vi.fn(), reset: vi.fn() }));

vi.mock("../../hooks/useBilling", () => ({
  useBilling: () => ({
    startCheckout,
    openPortal: vi.fn(),
    checkoutPending: false,
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
});
