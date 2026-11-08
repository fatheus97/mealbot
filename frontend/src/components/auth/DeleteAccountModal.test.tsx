import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { untranslatedEnglishIn } from "../../test/i18nAssertions";
import { useLocaleStore, DEFAULT_LOCALE } from "../../store/useLocaleStore";
import { DeleteAccountModal } from "./DeleteAccountModal";
import * as AuthCtx from "../../contexts/AuthContext";
import * as api from "../../api";
import type { AuthState, Household, HouseholdMember } from "../../types";

const ME_ALONE: HouseholdMember = { id: 1, email: "me@example.com" };

function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    email: "me@example.com",
    emailVerified: true,
    isDemo: false,
    isAdmin: false,
    isSubscribed: false,
    ...over,
  } as unknown as AuthState;
}

beforeEach(() => vi.restoreAllMocks());

describe("DeleteAccountModal", () => {
  it("sends the current password", async () => {
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    const del = vi.spyOn(api, "deleteAccount").mockResolvedValue(undefined);

    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    await user.click(screen.getByRole("button", { name: /delete my account/i }));

    await waitFor(() =>
      expect(del).toHaveBeenCalledWith("Secret123", expect.anything()),
    );
  });

  it("tells someone who shares a household what stays with it", async () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ householdsEnabled: true }));
    vi.spyOn(api, "fetchHousehold").mockResolvedValue({
      members: [
        { id: 1, email: "me@example.com" },
        { id: 2, email: "partner@example.com" },
      ],
      invites: [],
      max_members: 6,
      max_live_invites: 3,
    });
    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    expect(await screen.findByText(/Your household keeps the plans/)).toBeInTheDocument();
    expect(screen.queryByText(/Your plans, recipes, cookbook, fridge/)).toBeNull();
  });

  it("waits for the household before it can delete, and only until it arrives", async () => {
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ householdsEnabled: true }));
    let arrive: (household: Household) => void = () => {};
    vi.spyOn(api, "fetchHousehold").mockReturnValue(new Promise((resolve) => (arrive = resolve)));
    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    const submit = screen.getByRole("button", { name: /delete my account/i });
    expect(submit).toBeDisabled();

    arrive({ members: [ME_ALONE], invites: [], max_members: 6, max_live_invites: 3 });

    await waitFor(() => expect(submit).toBeEnabled());
    expect(screen.getByText(/Your plans, recipes, cookbook, fridge/)).toBeInTheDocument();
  });

  it("says what stays with a household when the household cannot be loaded", async () => {
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ householdsEnabled: true }));
    vi.spyOn(api, "fetchHousehold").mockRejectedValue(new Error("down"));
    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    expect(await screen.findByText(/Your household keeps the plans/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    expect(screen.getByRole("button", { name: /delete my account/i })).toBeEnabled();
  });

  it("asks nothing about households while they are off", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ householdsEnabled: false }));
    const fetched = vi.spyOn(api, "fetchHousehold");
    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    expect(screen.getByText(/Your plans, recipes, cookbook, fridge/)).toBeInTheDocument();
    expect(fetched).not.toHaveBeenCalled();
  });

  it("cannot be submitted without a password", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: /delete my account/i })).toBeDisabled();
  });

  it("drops local session state on success", async () => {
    // The server already destroyed the session, so the SPA must clear its own
    // state WITHOUT posting /auth/logout (a guaranteed 401 for a revocation
    // that already happened). `mealbot:logout` is that signal.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    vi.spyOn(api, "deleteAccount").mockResolvedValue(undefined);
    const onLogout = vi.fn();
    window.addEventListener("mealbot:logout", onLogout);

    try {
      renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
      await user.type(screen.getByLabelText(/current password/i), "Secret123");
      await user.click(screen.getByRole("button", { name: /delete my account/i }));
      await waitFor(() => expect(onLogout).toHaveBeenCalled());
    } finally {
      window.removeEventListener("mealbot:logout", onLogout);
    }
  });

  it("surfaces the server's reason verbatim", async () => {
    // The three answers need three different responses from the user: 401 is a
    // typo, 403 says this account type cannot self-delete, and 503 means the
    // subscription could not be cancelled so NOTHING was deleted. Collapsing
    // them into "couldn't delete it" would hide the one that means "retry".
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    vi.spyOn(api, "deleteAccount").mockRejectedValue(
      new Error("We could not cancel your subscription with our payment provider"),
    );

    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    await user.click(screen.getByRole("button", { name: /delete my account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not cancel your subscription/i,
    );
    // Still usable: a 503 means nothing was deleted, so retrying is the point.
    expect(screen.getByRole("button", { name: /delete my account/i })).toBeEnabled();
  });

  it("warns about the forfeited period only when subscribed", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ isSubscribed: true }));
    const { unmount } = renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    expect(screen.getByText(/not refunded/i)).toBeInTheDocument();
    unmount();

    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ isSubscribed: false }));
    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    expect(screen.queryByText(/not refunded/i)).not.toBeInTheDocument();
  });

  it("tells the user to export first", () => {
    // The order matters more than the sentence: once this succeeds there is
    // nothing left to export.
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
    expect(screen.getByText(/download your data first/i)).toBeInTheDocument();
  });

  describe("in Czech", () => {
    beforeEach(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    afterEach(() =>
      useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false }),
    );

    it("renders no untranslated English", () => {
      vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ isSubscribed: true }));
      renderWithProviders(<DeleteAccountModal onClose={vi.fn()} />);
      expect(untranslatedEnglishIn(document.body)).toEqual([]);
    });
  });
});
