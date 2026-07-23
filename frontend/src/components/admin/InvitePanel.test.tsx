import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { InvitePanel } from "./InvitePanel";
import * as api from "../../api";
import type { InviteListResponse } from "../../types";

vi.mock("../../api", () => ({
  // AuthProvider calls authFetch("/config") on mount — stub it.
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  fetchInvites: vi.fn(),
  createInvite: vi.fn(),
  revokeInvite: vi.fn(),
}));

const listResp: InviteListResponse = {
  invites: [
    {
      id: 1,
      note: "for Alice",
      is_comped: true,
      status: "live",
      created_at: "2026-07-23T10:00:00Z",
      expires_at: "2026-07-25T10:00:00Z",
      redeemed_by_email: null,
    },
    {
      id: 2,
      note: null,
      is_comped: false,
      status: "used",
      created_at: "2026-07-22T10:00:00Z",
      expires_at: "2026-07-24T10:00:00Z",
      redeemed_by_email: "bob@example.com",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  vi.mocked(api.fetchInvites).mockResolvedValue(listResp);
});

describe("InvitePanel", () => {
  it("lists invites with status badges and the redeemer email", async () => {
    renderWithProviders(<InvitePanel />);
    expect(await screen.findByText("for Alice")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText("Used")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  });

  it("generates a link and surfaces the copyable URL once", async () => {
    vi.mocked(api.createInvite).mockResolvedValue({
      id: 9,
      invite_url: "http://localhost:5173/?invite=abc123",
      expires_at: "2026-07-25T10:00:00Z",
      is_comped: true,
      note: null,
    });
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("for Alice");

    await user.click(screen.getByRole("button", { name: /generate invite link/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Generate" }));

    // Comp defaults on; the chosen expiry (48h default) rides along.
    await waitFor(() =>
      expect(api.createInvite).toHaveBeenCalledWith(
        expect.objectContaining({ is_comped: true, expires_in_hours: 48 }),
      ),
    );
    // The full one-time link is shown for copying, with the "shown once" warning.
    expect(
      await screen.findByDisplayValue("http://localhost:5173/?invite=abc123"),
    ).toBeInTheDocument();
    expect(screen.getByText(/won't be able to see it again/i)).toBeInTheDocument();
  });

  it("revokes a live invite through a confirm dialog", async () => {
    vi.mocked(api.revokeInvite).mockResolvedValue({
      ...listResp.invites[0],
      status: "revoked",
    });
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("for Alice");

    // Only the live invite has a Revoke button (the used one does not).
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(api.revokeInvite).toHaveBeenCalledWith(1));
  });

  it("only shows a Revoke action for live invites", async () => {
    renderWithProviders(<InvitePanel />);
    await screen.findByText("for Alice");
    // Two invites (one live, one used) → exactly one Revoke button.
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(1);
  });
});
