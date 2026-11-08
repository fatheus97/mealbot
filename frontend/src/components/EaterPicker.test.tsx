import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { renderWithProviders } from "../test/test-utils";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { EaterPicker } from "./EaterPicker";
import * as AuthCtx from "../contexts/AuthContext";
import * as api from "../api";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import type { AuthState, DietaryProfile, Household, HouseholdMember } from "../types";

function authState(over: Partial<AuthState> = {}): AuthState {
  return { userId: 1, isDemo: false, householdsEnabled: true, ...over } as unknown as AuthState;
}

function profile(over: Partial<DietaryProfile> = {}): DietaryProfile {
  return { diet_types: [], allergens: [], avoid_ingredients: [], updated_at: "2026-11-05T10:00:00Z", ...over };
}

const ME: HouseholdMember = {
  id: 1,
  email: "me@example.com",
  profile: profile({ diet_types: ["vegetarian"], allergens: ["milk"] }),
  needs_consent: false,
};
const PARTNER: HouseholdMember = {
  id: 2,
  email: "partner@example.com",
  profile: profile({ allergens: ["eggs", "milk"], avoid_ingredients: ["coriander"] }),
  needs_consent: false,
};
// What the server sends for a partner whose consent lapsed: no profile.
const LAPSED: HouseholdMember = { ...PARTNER, profile: null, needs_consent: true };

function household(members: HouseholdMember[]): Household {
  return { members, invites: [], max_members: 6, max_live_invites: 3 };
}

let seen: (number[] | null)[] = [];
function Harness() {
  const [eaters, setEaters] = useState<number[] | null>(null);
  return (
    <EaterPicker
      eaters={eaters}
      onChange={(next) => {
        seen.push(next);
        setEaters(next);
      }}
    />
  );
}

function setUp(members: HouseholdMember[] = [ME, PARTNER], state: AuthState = authState()) {
  vi.spyOn(AuthCtx, "useAuth").mockReturnValue(state);
  return vi.spyOn(api, "fetchHousehold").mockResolvedValue(household(members));
}

beforeEach(() => {
  vi.restoreAllMocks();
  seen = [];
});
afterEach(() => act(() => useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false })));

describe("EaterPicker", () => {
  it("shows nothing to someone alone in their household", async () => {
    const fetched = setUp([ME]);
    const { container } = renderWithProviders(<Harness />);
    await vi.waitFor(() => expect(fetched).toHaveBeenCalled());
    // Let the household arrive and render before looking.
    await act(async () => {
      await fetched.mock.results[0].value;
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("asks for nothing while households are off, or in a demo", () => {
    const fetched = setUp([ME, PARTNER], authState({ householdsEnabled: false }));
    renderWithProviders(<Harness />);
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ isDemo: true }));
    renderWithProviders(<Harness />);
    expect(fetched).not.toHaveBeenCalled();
    expect(screen.queryByText("Who's eating")).toBeNull();
  });

  it("ticks everyone, marks you, and shows the union of what they saved", async () => {
    setUp();
    renderWithProviders(<Harness />);
    const me = await screen.findByLabelText("me@example.com (you)");
    expect(me).toBeChecked();
    expect(screen.getByLabelText("partner@example.com")).toBeChecked();
    expect(screen.getByText("Diets: Vegetarian")).toBeInTheDocument();
    expect(screen.getByText("Allergies: Milk / dairy, Eggs")).toBeInTheDocument();
    expect(screen.getByText("Avoid: coriander")).toBeInTheDocument();
  });

  it("drops an unticked person's diets from the summary and names who is left", async () => {
    setUp();
    renderWithProviders(<Harness />);
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("partner@example.com"));
    expect(seen).toEqual([[1]]);
    expect(screen.getByText("Allergies: Milk / dairy")).toBeInTheDocument();
    expect(screen.queryByText(/coriander/)).toBeNull();
  });

  it("goes back to everyone, which sends nothing, once all are ticked again", async () => {
    setUp();
    renderWithProviders(<Harness />);
    const user = userEvent.setup();
    const partner = await screen.findByLabelText("partner@example.com");
    await user.click(partner);
    await user.click(partner);
    expect(seen).toEqual([[1], null]);
  });

  it("says so when nobody ticked has anything saved", async () => {
    setUp([
      { ...ME, profile: null },
      { ...PARTNER, profile: null },
    ]);
    renderWithProviders(<Harness />);
    expect(await screen.findByText("The people ticked have no diets or allergies saved.")).toBeInTheDocument();
  });

  it("warns that baby food applies to every meal", async () => {
    setUp([ME, { ...PARTNER, profile: profile({ diet_types: ["baby_food"] }) }]);
    renderWithProviders(<Harness />);
    expect(await screen.findByText(/Baby food applies to every meal/)).toBeInTheDocument();
  });

  it("names someone ticked whose consent the server says is missing, and stops once they are unticked", async () => {
    setUp([ME, LAPSED]);
    renderWithProviders(<Harness />);
    const user = userEvent.setup();
    expect(await screen.findByText(/partner@example.com hasn't confirmed consent/)).toBeInTheDocument();
    // Their data is not shown without consent, so the summary is only yours.
    expect(screen.getByText("Allergies: Milk / dairy")).toBeInTheDocument();
    await user.click(screen.getByLabelText("partner@example.com"));
    expect(screen.queryByText(/hasn't confirmed consent/)).toBeNull();
  });

  it("names nobody the server does not flag", async () => {
    setUp([ME, { ...PARTNER, profile: null }]);
    renderWithProviders(<Harness />);
    await screen.findByLabelText("partner@example.com");
    expect(screen.queryByText(/hasn't confirmed consent/)).toBeNull();
  });

  it("is all Czech in a Czech UI", async () => {
    setUp([ME, LAPSED]);
    act(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    renderWithProviders(<Harness />);
    expect(await screen.findByText("Kdo bude jíst")).toBeInTheDocument();
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });
});
