import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { HealthConsentSettings } from "./HealthConsentSettings";
import * as AuthCtx from "../contexts/AuthContext";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import type { AuthState } from "../types";

function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    healthConsent: true,
    healthConsentAt: "2026-11-01T10:00:00",
    withdrawHealthConsent: vi.fn().mockResolvedValue(undefined),
    ...over,
  } as unknown as AuthState;
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() =>
  act(() => useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false })),
);

describe("HealthConsentSettings", () => {
  it("says when consent was given", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<HealthConsentSettings />);
    expect(screen.getByText(/you consented to mealbot processing/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Withdraw consent" })).toBeInTheDocument();
  });

  it("withdraws only after the confirm, which replaces the button in place", async () => {
    const state = authState();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(state);
    renderWithProviders(<HealthConsentSettings />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Withdraw consent" }));
    expect(state.withdrawHealthConsent).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Withdraw consent" })).toBeNull();
    expect(screen.getByText(/removes your diets, allergies and ingredients to avoid/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(state.withdrawHealthConsent).toHaveBeenCalledTimes(1);
  });

  it("cancel keeps the consent", async () => {
    const state = authState();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(state);
    renderWithProviders(<HealthConsentSettings />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Withdraw consent" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(state.withdrawHealthConsent).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Withdraw consent" })).toBeInTheDocument();
  });

  it("reports a failed withdrawal", async () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ withdrawHealthConsent: vi.fn().mockRejectedValue(new Error("boom")) }),
    );
    renderWithProviders(<HealthConsentSettings />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Withdraw consent" }));
    await user.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't withdraw/i);
  });

  it("offers the consent itself, and nothing to withdraw, without consent", async () => {
    // Consenting must not depend on what the planner form happens to hold.
    const grantHealthConsent = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ healthConsent: false, healthConsentAt: null, grantHealthConsent }),
    );
    renderWithProviders(<HealthConsentSettings />);
    expect(screen.getByText(/haven't consented/i)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    await userEvent.setup().click(screen.getByRole("checkbox", { name: /i consent/i }));
    expect(grantHealthConsent).toHaveBeenCalledTimes(1);
  });

  it("still offers withdrawal of a consent to an older text", () => {
    // After a consent-text bump the server no longer counts it as current, but
    // the data given under it is still stored: withdrawing must stay one click.
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ healthConsent: false, healthConsentAt: "2026-11-01T10:00:00" }),
    );
    renderWithProviders(<HealthConsentSettings />);
    expect(screen.getByRole("button", { name: "Withdraw consent" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /i consent/i })).toBeInTheDocument();
  });

  it("speaks Czech in a Czech UI", () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<HealthConsentSettings />);
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });
});
