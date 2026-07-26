import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { InvitePanel } from "./InvitePanel";
import * as api from "../../api";
import type { AccessRequestListResponse, InviteListResponse } from "../../types";

vi.mock("../../api", () => ({
  // AuthProvider calls authFetch("/config") on mount — stub it.
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  fetchInvites: vi.fn(),
  createInvite: vi.fn(),
  revokeInvite: vi.fn(),
  fetchAccessRequests: vi.fn(),
  updateAccessRequest: vi.fn(),
  deleteAccessRequest: vi.fn(),
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

const accessResp: AccessRequestListResponse = {
  requests: [
    {
      id: 11,
      email: "carol@example.com",
      message: "vegan + nut allergy household",
      status: "pending",
      created_at: "2026-07-26T09:00:00Z",
      handled_at: null,
      has_account: false,
    },
    {
      id: 12,
      email: "dave@example.com",
      message: "",
      status: "pending",
      created_at: "2026-07-26T08:00:00Z",
      handled_at: null,
      has_account: true,
    },
  ],
  pending_count: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  vi.mocked(api.fetchInvites).mockResolvedValue(listResp);
  vi.mocked(api.fetchAccessRequests).mockResolvedValue(accessResp);
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

describe("InvitePanel — access requests", () => {
  it("lists pending requests with the pending badge", async () => {
    renderWithProviders(<InvitePanel />);
    expect(await screen.findByText("carol@example.com")).toBeInTheDocument();
    expect(screen.getByText("vegan + nut allergy household")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /access requests/i })).toBeInTheDocument();
  });

  it("flags a requester who already has an account", async () => {
    renderWithProviders(<InvitePanel />);
    await screen.findByText("dave@example.com");
    // The admin-only signal the public endpoint withholds.
    expect(screen.getByText(/already has an account/i)).toBeInTheDocument();
  });

  it("dismisses a request", async () => {
    vi.mocked(api.updateAccessRequest).mockResolvedValue({
      ...accessResp.requests[0],
      status: "dismissed",
    });
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("carol@example.com");

    const row = screen.getByText("carol@example.com").closest("tr")!;
    await user.click(within(row).getByRole("button", { name: /dismiss/i }));

    await waitFor(() =>
      expect(api.updateAccessRequest).toHaveBeenCalledWith(11, "dismissed"),
    );
  });

  it("generating an invite from a request prefills the note AND marks it handled", async () => {
    // The whole point of the queue: one click from "someone asked" to
    // "they have a link", without leaving the tab.
    vi.mocked(api.createInvite).mockResolvedValue({
      id: 9,
      invite_url: "http://localhost:5173/app?invite=abc123",
      expires_at: "2026-07-28T10:00:00Z",
      is_comped: true,
      note: "Access request: carol@example.com",
    });
    vi.mocked(api.updateAccessRequest).mockResolvedValue({
      ...accessResp.requests[0],
      status: "handled",
    });
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("carol@example.com");

    const row = screen.getByText("carol@example.com").closest("tr")!;
    await user.click(within(row).getByRole("button", { name: /generate invite/i }));

    const dialog = await screen.findByRole("dialog");
    // Prefilled with the request ID, deliberately NOT the email: invite notes
    // are not touched by the access-request DELETE, so putting the address
    // here would leave a second copy that GDPR erasure can't reach. The id is
    // enough to correlate back to the (erasable) request row.
    expect(within(dialog).getByDisplayValue("Access request #11")).toBeInTheDocument();
    expect(within(dialog).queryByDisplayValue(/carol@example\.com/)).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(api.createInvite).toHaveBeenCalled());
    await waitFor(() =>
      expect(api.updateAccessRequest).toHaveBeenCalledWith(11, "handled"),
    );
  });

  it("still shows the invite link when marking the request handled fails", async () => {
    // The link is the valuable artifact and it already exists — a bookkeeping
    // failure must not read as "the invite failed".
    vi.mocked(api.createInvite).mockResolvedValue({
      id: 9,
      invite_url: "http://localhost:5173/app?invite=abc123",
      expires_at: "2026-07-28T10:00:00Z",
      is_comped: true,
      note: null,
    });
    vi.mocked(api.updateAccessRequest).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("carol@example.com");

    const row = screen.getByText("carol@example.com").closest("tr")!;
    await user.click(within(row).getByRole("button", { name: /generate invite/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Generate" }));

    expect(
      await within(dialog).findByDisplayValue("http://localhost:5173/app?invite=abc123"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/couldn't be marked handled/i),
    );
  });

  it("deletes a request only after confirming (GDPR erasure)", async () => {
    vi.mocked(api.deleteAccessRequest).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("carol@example.com");

    const row = screen.getByText("carol@example.com").closest("tr")!;
    await user.click(within(row).getByRole("button", { name: /delete/i }));
    expect(api.deleteAccessRequest).not.toHaveBeenCalled();

    const confirm = await screen.findByRole("dialog");
    await user.click(within(confirm).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(api.deleteAccessRequest).toHaveBeenCalledWith(11));
  });

  it("refetches with a status filter when switching tabs", async () => {
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("carol@example.com");

    await user.click(screen.getByRole("button", { name: "handled" }));
    await waitFor(() => expect(api.fetchAccessRequests).toHaveBeenCalledWith("handled"));
  });
});

describe("InvitePanel — access request row actions", () => {
  it("offers the Mark handled action the failure banner tells the admin to use", async () => {
    vi.mocked(api.updateAccessRequest).mockResolvedValue({
      ...accessResp.requests[0],
      status: "handled",
    });
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("carol@example.com");

    const row = screen.getByText("carol@example.com").closest("tr")!;
    await user.click(within(row).getByRole("button", { name: /mark handled/i }));
    await waitFor(() => expect(api.updateAccessRequest).toHaveBeenCalledWith(11, "handled"));
  });

  it("does not disable OTHER rows' actions while one row is in flight", async () => {
    // One shared mutation instance would otherwise freeze every row.
    vi.mocked(api.updateAccessRequest).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderWithProviders(<InvitePanel />);
    await screen.findByText("carol@example.com");

    const carol = screen.getByText("carol@example.com").closest("tr")!;
    const dave = screen.getByText("dave@example.com").closest("tr")!;
    await user.click(within(carol).getByRole("button", { name: /dismiss/i }));

    await waitFor(() =>
      expect(within(carol).getByRole("button", { name: /dismiss/i })).toBeDisabled(),
    );
    expect(within(dave).getByRole("button", { name: /dismiss/i })).not.toBeDisabled();
  });
});
