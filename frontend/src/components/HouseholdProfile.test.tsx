import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { HouseholdProfile } from "./HouseholdProfile";
import * as AuthCtx from "../contexts/AuthContext";
import * as api from "../api";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import type { AuthState, DietaryProfile } from "../types";

function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    healthConsent: true,
    healthConsentAt: "2026-11-01T10:00:00",
    grantHealthConsent: vi.fn().mockResolvedValue(undefined),
    ...over,
  } as unknown as AuthState;
}

const SAVED: DietaryProfile = {
  diet_types: ["vegetarian", "something_dropped_later"],
  allergens: ["milk"],
  avoid_ingredients: ["coriander"],
  updated_at: "2026-11-05T10:00:00Z",
};

function setUp(profile: DietaryProfile | null = SAVED, state: AuthState = authState()) {
  vi.spyOn(AuthCtx, "useAuth").mockReturnValue(state);
  vi.spyOn(api, "fetchDietaryProfile").mockResolvedValue(profile);
}

const pressed = (name: string) =>
  screen.getByRole("button", { name }).getAttribute("aria-pressed") === "true";

beforeEach(() => vi.restoreAllMocks());
afterEach(() => act(() => useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false })));

describe("HouseholdProfile", () => {
  it("shows what is saved, and nothing to save until something changes", async () => {
    setUp();
    renderWithProviders(<HouseholdProfile />);
    await screen.findByText(/^Last saved /);
    expect(pressed("Vegetarian")).toBe(true);
    expect(screen.getByText("coriander")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("saves the edited lists, leaving out a value the app no longer knows", async () => {
    setUp();
    const save = vi.spyOn(api, "saveDietaryProfile").mockResolvedValue({
      ...SAVED,
      diet_types: ["vegetarian"],
      allergens: ["milk", "eggs"],
    });
    renderWithProviders(<HouseholdProfile />);
    const user = userEvent.setup();
    await screen.findByText(/^Last saved /);

    await user.click(screen.getByRole("button", { name: "Eggs" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(save).toHaveBeenCalledWith(
      { diet_types: ["vegetarian"], allergens: ["milk", "eggs"], avoid_ingredients: ["coriander"] },
      expect.anything(),
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(pressed("Eggs")).toBe(true);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("asks for consent before saving health data, and waits for it", async () => {
    setUp(null, authState({ healthConsent: false, healthConsentAt: null }));
    const save = vi.spyOn(api, "saveDietaryProfile");
    renderWithProviders(<HouseholdProfile />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Milk / dairy" }));

    expect(screen.getByRole("checkbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
  });

  it("cancel puts back what is saved", async () => {
    setUp();
    renderWithProviders(<HouseholdProfile />);
    const user = userEvent.setup();
    await screen.findByText(/^Last saved /);
    await user.click(screen.getByRole("button", { name: "Vegetarian" }));
    expect(pressed("Vegetarian")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(pressed("Vegetarian")).toBe(true);
  });

  it("says why a save was refused", async () => {
    setUp();
    vi.spyOn(api, "saveDietaryProfile").mockRejectedValue(new Error("Consent for this is missing."));
    renderWithProviders(<HouseholdProfile />);
    const user = userEvent.setup();
    await screen.findByText(/^Last saved /);
    await user.click(screen.getByRole("button", { name: "Eggs" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Consent for this is missing.");
  });

  it("removes the saved profile only after the confirm", async () => {
    setUp();
    const remove = vi.spyOn(api, "deleteDietaryProfile").mockResolvedValue(undefined);
    renderWithProviders(<HouseholdProfile />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Remove saved diets and allergies" }));
    expect(remove).not.toHaveBeenCalled();
    expect(screen.getByText(/withdraw your consent below/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove" }));

    expect(remove).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(pressed("Vegetarian")).toBe(false));
    expect(screen.queryByRole("button", { name: "Remove saved diets and allergies" })).toBeNull();
  });

  it("offers no removal when nothing is saved", async () => {
    setUp(null);
    renderWithProviders(<HouseholdProfile />);
    await screen.findByRole("button", { name: "Save" });
    expect(screen.queryByRole("button", { name: "Remove saved diets and allergies" })).toBeNull();
  });

  it("is all Czech in a Czech UI", async () => {
    setUp();
    act(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    renderWithProviders(<HouseholdProfile />);
    expect(await screen.findByText("Vaše uložené diety a alergie")).toBeInTheDocument();
    await screen.findByText(/Naposledy uloženo/);
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });
});
