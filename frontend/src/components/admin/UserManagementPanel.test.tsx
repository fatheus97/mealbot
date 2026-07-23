import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { UserManagementPanel } from "./UserManagementPanel";
import * as api from "../../api";
import type { AdminUser, AdminUserListResponse } from "../../types";

vi.mock("../../api", () => ({
  // AuthProvider calls authFetch("/config") on mount — stub it.
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  fetchAdminUsers: vi.fn(),
  createAdminUser: vi.fn(),
  updateAdminUser: vi.fn(),
  resetAdminUserOnboarding: vi.fn(),
  forceLogoutAdminUser: vi.fn(),
}));

function mkUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: 1,
    email: "alice@example.com",
    created_at: "2026-07-01T00:00:00Z",
    is_active: true,
    is_admin: false,
    is_demo: false,
    is_comped: false,
    onboarding_completed: false,
    country: null,
    subscription_status: "none",
    current_period_end: null,
    ...overrides,
  };
}

function listResp(users: AdminUser[], total?: number): AdminUserListResponse {
  return { total: total ?? users.length, limit: 25, offset: 0, users };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp([mkUser()]));
});

describe("UserManagementPanel", () => {
  it("renders the users table", async () => {
    renderWithProviders(<UserManagementPanel />);
    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
  });

  it("debounces the search box into a filtered fetch", async () => {
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("alice@example.com");

    await user.type(screen.getByLabelText("Search users by email"), "bob");
    await waitFor(() =>
      expect(api.fetchAdminUsers).toHaveBeenCalledWith(expect.objectContaining({ q: "bob" })),
    );
  });

  it("filters by status", async () => {
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("alice@example.com");

    await user.selectOptions(screen.getByLabelText("Filter by status"), "disabled");
    await waitFor(() =>
      expect(api.fetchAdminUsers).toHaveBeenCalledWith(expect.objectContaining({ status: "disabled" })),
    );
  });

  it("makes a user an admin via the row action (no confirm needed)", async () => {
    const u = mkUser({ id: 7, email: "bob@example.com", is_admin: false });
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp([u]));
    vi.mocked(api.updateAdminUser).mockResolvedValue({ ...u, is_admin: true });
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("bob@example.com");

    await user.click(screen.getByRole("button", { name: "Make admin" }));
    await waitFor(() =>
      expect(api.updateAdminUser).toHaveBeenCalledWith(7, { is_admin: true }),
    );
  });

  it("deactivates through a confirm dialog", async () => {
    const u = mkUser({ id: 3, email: "carol@example.com", is_active: true });
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp([u]));
    vi.mocked(api.updateAdminUser).mockResolvedValue({ ...u, is_active: false });
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("carol@example.com");

    await user.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() =>
      expect(api.updateAdminUser).toHaveBeenCalledWith(3, { is_active: false }),
    );
  });

  it("surfaces a last-admin 409 inside the confirm dialog and keeps it open", async () => {
    const u = mkUser({ id: 9, email: "solo-admin@example.com", is_active: true, is_admin: true });
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp([u]));
    vi.mocked(api.updateAdminUser).mockRejectedValue(
      new Error("Cannot remove the last active admin."),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("solo-admin@example.com");

    await user.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    expect(await within(dialog).findByText(/last active admin/i)).toBeInTheDocument();
    // Dialog stays open on error.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows no row actions for a demo account", async () => {
    const demo = mkUser({ id: 5, email: "demo@example.com", is_demo: true });
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp([demo]));
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("demo@example.com");

    expect(screen.queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make admin" })).not.toBeInTheDocument();
  });

  it("force-logs-out through a confirm dialog", async () => {
    const u = mkUser({ id: 4, email: "dave@example.com" });
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp([u]));
    vi.mocked(api.forceLogoutAdminUser).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("dave@example.com");

    await user.click(screen.getByRole("button", { name: "Force logout" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Log out" }));

    await waitFor(() => expect(api.forceLogoutAdminUser).toHaveBeenCalledWith(4));
  });

  it("creates a user via the modal form", async () => {
    vi.mocked(api.createAdminUser).mockResolvedValue(
      mkUser({ id: 12, email: "new@example.com" }),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("alice@example.com");

    await user.click(screen.getByRole("button", { name: "+ New user" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Email"), "new@example.com");
    await user.type(within(dialog).getByLabelText("Password"), "NewPass123");
    await user.click(within(dialog).getByLabelText("Admin access"));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(api.createAdminUser).toHaveBeenCalledWith(
        expect.objectContaining({ email: "new@example.com", password: "NewPass123", is_admin: true }),
      ),
    );
  });
});
