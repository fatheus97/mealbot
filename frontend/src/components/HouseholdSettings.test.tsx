import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { stubLocationReload } from "../test/location";
import { HouseholdSettings } from "./HouseholdSettings";
import * as AuthCtx from "../contexts/AuthContext";
import * as api from "../api";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import type { AuthState, Household } from "../types";

function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    email: "me@example.com",
    isDemo: false,
    householdsEnabled: true,
    ...over,
  } as unknown as AuthState;
}

function household(over: Partial<Household> = {}): Household {
  return {
    members: [{ id: 1, email: "me@example.com" }],
    invites: [],
    max_members: 6,
    max_live_invites: 3,
    ...over,
  };
}

const SHARED = household({
  members: [
    { id: 1, email: "me@example.com" },
    { id: 2, email: "partner@example.com" },
  ],
});

function setUp(state: AuthState = authState(), data: Household = household()) {
  vi.spyOn(AuthCtx, "useAuth").mockReturnValue(state);
  return vi.spyOn(api, "fetchHousehold").mockResolvedValue(data);
}

beforeEach(() => {
  vi.restoreAllMocks();
  stubLocationReload();
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false }));
});

describe("HouseholdSettings", () => {
  it("shows nothing and asks for nothing while households are off", () => {
    const fetched = setUp(authState({ householdsEnabled: false }));
    const { container } = renderWithProviders(<HouseholdSettings />);
    expect(container).toBeEmptyDOMElement();
    expect(fetched).not.toHaveBeenCalled();
  });

  it("shows nothing to a demo session, which can never share a kitchen", () => {
    const fetched = setUp(authState({ isDemo: true }));
    const { container } = renderWithProviders(<HouseholdSettings />);
    expect(container).toBeEmptyDOMElement();
    expect(fetched).not.toHaveBeenCalled();
  });

  it("lists the members and marks you", async () => {
    setUp(authState(), SHARED);
    renderWithProviders(<HouseholdSettings />);
    const list = await screen.findByRole("list", { name: "Members" });
    expect(list).toHaveTextContent("me@example.com (you)");
    expect(list).toHaveTextContent("partner@example.com");
    expect(list).not.toHaveTextContent("partner@example.com (you)");
  });

  it("shows a new invite's code once, with a way to copy it", async () => {
    setUp();
    const create = vi.spyOn(api, "createHouseholdInvite").mockResolvedValue({
      id: 7,
      email: "partner@example.com",
      expires_at: "2026-11-10T10:00:00Z",
      code: "the-secret-code",
    });
    renderWithProviders(<HouseholdSettings />);
    const user = userEvent.setup();
    // After setup: it replaces navigator.clipboard with its own.
    const write = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);

    await user.type(await screen.findByLabelText("Their email address"), " partner@example.com ");
    await user.click(screen.getByRole("button", { name: "Create invite code" }));

    expect(create).toHaveBeenCalledWith("partner@example.com", expect.anything());
    expect(await screen.findByDisplayValue("the-secret-code")).toBeInTheDocument();
    expect(screen.getByText(/You won't see it again/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(write).toHaveBeenCalledWith("the-secret-code");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("says why an invite was refused", async () => {
    setUp();
    vi.spyOn(api, "createHouseholdInvite").mockRejectedValue(
      new Error("This person is already in your household."),
    );
    renderWithProviders(<HouseholdSettings />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Their email address"), "a@example.com");
    await user.click(screen.getByRole("button", { name: "Create invite code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already in your household");
  });

  it("revokes an open invite", async () => {
    setUp(
      authState(),
      household({ invites: [{ id: 5, email: "a@example.com", expires_at: "2026-11-10T10:00:00Z" }] }),
    );
    const revoke = vi.spyOn(api, "revokeHouseholdInvite").mockResolvedValue(undefined);
    renderWithProviders(<HouseholdSettings />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Revoke" }));
    expect(revoke).toHaveBeenCalledWith(5, expect.anything());
  });

  it("offers no invite once the household is full", async () => {
    setUp(
      authState(),
      household({
        members: Array.from({ length: 6 }, (_, n) => ({ id: n + 1, email: `m${n}@example.com` })),
      }),
    );
    renderWithProviders(<HouseholdSettings />);
    expect(await screen.findByText("This household is full (6 members).")).toBeInTheDocument();
    expect(screen.queryByLabelText("Their email address")).toBeNull();
  });

  it("joins with a code and reloads, since every cache belongs to the old kitchen", async () => {
    setUp();
    const join = vi.spyOn(api, "joinHousehold").mockResolvedValue(undefined);
    renderWithProviders(<HouseholdSettings />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Invite code"), "  abc123  ");
    await user.click(screen.getByRole("button", { name: "Join" }));
    expect(join).toHaveBeenCalledWith("abc123", expect.anything());
    await waitFor(() => expect(window.location.reload).toHaveBeenCalledTimes(1));
  });

  it("stays put and says why when a join is refused", async () => {
    setUp();
    vi.spyOn(api, "joinHousehold").mockRejectedValue(new Error("This invite no longer exists."));
    renderWithProviders(<HouseholdSettings />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Invite code"), "abc");
    await user.click(screen.getByRole("button", { name: "Join" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This invite no longer exists.");
    expect(window.location.reload).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Join" })).toBeEnabled();
  });

  it("offers leaving, not joining, to someone who shares, and leaves only after the confirm", async () => {
    setUp(authState(), SHARED);
    const leave = vi.spyOn(api, "leaveHousehold").mockResolvedValue(undefined);
    renderWithProviders(<HouseholdSettings />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Leave household" }));
    expect(screen.queryByLabelText("Invite code")).toBeNull();
    expect(leave).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Leave household" })).toBeNull();
    expect(screen.getByText(/You keep your saved profile/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Leave" }));
    expect(leave).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(window.location.reload).toHaveBeenCalledTimes(1));
  });

  it("cancelling the leave changes nothing", async () => {
    setUp(authState(), SHARED);
    const leave = vi.spyOn(api, "leaveHousehold").mockResolvedValue(undefined);
    renderWithProviders(<HouseholdSettings />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Leave household" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(leave).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Leave household" })).toBeInTheDocument();
  });

  it("says so when the household cannot be loaded", async () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    vi.spyOn(api, "fetchHousehold").mockRejectedValue(new Error("Household failed: 500"));
    renderWithProviders(<HouseholdSettings />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load your household.");
  });

  it("is all Czech in a Czech UI", async () => {
    setUp(
      authState(),
      household({
        members: SHARED.members,
        invites: [{ id: 5, email: "a@example.com", expires_at: "2026-11-10T10:00:00Z" }],
      }),
    );
    act(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    renderWithProviders(<HouseholdSettings />);
    expect(await screen.findByText("Domácnost")).toBeInTheDocument();
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });
});
