import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { HealthConsentCheckbox } from "./HealthConsentCheckbox";
import * as AuthCtx from "../contexts/AuthContext";
import { HealthConsentStaleError } from "../api";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import type { AuthState } from "../types";

function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    healthConsent: false,
    healthConsentAt: null,
    grantHealthConsent: vi.fn().mockResolvedValue(undefined),
    ...over,
  } as unknown as AuthState;
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() =>
  act(() => useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false })),
);

describe("HealthConsentCheckbox", () => {
  it("asks, unticked, while the form carries diet data and there is no consent", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<HealthConsentCheckbox active />);
    const box = screen.getByRole("checkbox");
    expect(box).not.toBeChecked();
    // The sentence names what is processed, why, who receives it, and how to withdraw.
    const label = box.closest("label")!.textContent!;
    for (const part of ["diets, allergies and ingredients to avoid", "Google and OpenAI", "in the US", "withdraw"]) {
      expect(label).toContain(part);
    }
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
  });

  it("stays hidden when the form carries no diet data", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<HealthConsentCheckbox active={false} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("stays hidden once the user has consented", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ healthConsent: true }));
    renderWithProviders(<HealthConsentCheckbox active />);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("records the consent when ticked", async () => {
    const state = authState();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(state);
    renderWithProviders(<HealthConsentCheckbox active />);
    await userEvent.setup().click(screen.getByRole("checkbox"));
    expect(state.grantHealthConsent).toHaveBeenCalledTimes(1);
  });

  it("says the text changed when the server wants a newer version", async () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ grantHealthConsent: vi.fn().mockRejectedValue(new HealthConsentStaleError()) }),
    );
    renderWithProviders(<HealthConsentCheckbox active />);
    await userEvent.setup().click(screen.getByRole("checkbox"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/consent text changed/i);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("says saving failed on any other error", async () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ grantHealthConsent: vi.fn().mockRejectedValue(new Error("boom")) }),
    );
    renderWithProviders(<HealthConsentCheckbox active />);
    await userEvent.setup().click(screen.getByRole("checkbox"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't save your consent/i);
  });

  it("speaks Czech and links the Czech policy in a Czech UI", () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<HealthConsentCheckbox active />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/cs/privacy");
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });
});
