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
  deleteAdminUser: vi.fn(),
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

  it("deletes a user only after the email is typed to confirm", async () => {
    const u = mkUser({ id: 8, email: "erase@example.com" });
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp([u]));
    vi.mocked(api.deleteAdminUser).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("erase@example.com");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    const confirmBtn = within(dialog).getByRole("button", { name: /Delete permanently/ });
    const field = within(dialog).getByLabelText("Type the email to confirm");

    // Empty → disabled.
    expect(confirmBtn).toBeDisabled();
    // A NON-matching value must keep it disabled — this pins the email-EQUALITY
    // gate (a "non-empty" mutation would wrongly enable here).
    await user.type(field, "wrong@example.com");
    expect(confirmBtn).toBeDisabled();
    // The exact email enables it.
    await user.clear(field);
    await user.type(field, "erase@example.com");
    expect(confirmBtn).toBeEnabled();
    await user.click(confirmBtn);

    await waitFor(() => expect(api.deleteAdminUser).toHaveBeenCalledWith(8));
  });

  it("selects rows and bulk-deactivates them", async () => {
    const users = [mkUser({ id: 1, email: "a@example.com" }), mkUser({ id: 2, email: "b@example.com" })];
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp(users));
    vi.mocked(api.updateAdminUser).mockResolvedValue(mkUser());
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("a@example.com");

    await user.click(screen.getByLabelText("Select all users on this page"));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    const bar = screen.getByRole("region", { name: "Bulk actions" });
    await user.click(within(bar).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => {
      expect(api.updateAdminUser).toHaveBeenCalledWith(1, { is_active: false });
      expect(api.updateAdminUser).toHaveBeenCalledWith(2, { is_active: false });
    });
    // Green summary banner, plural-correct ("users", not "user").
    expect(await screen.findByText("Deactivated 2 users.")).toBeInTheDocument();
  });

  it("bulk-reactivates the selection", async () => {
    const users = [
      mkUser({ id: 1, email: "a@example.com", is_active: false }),
      mkUser({ id: 2, email: "b@example.com", is_active: false }),
    ];
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp(users));
    vi.mocked(api.updateAdminUser).mockResolvedValue(mkUser());
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("a@example.com");

    await user.click(screen.getByLabelText("Select all users on this page"));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    await user.click(within(bar).getByRole("button", { name: "Reactivate" }));

    // Distinct payload from Deactivate — is_active:true — for every selected id.
    await waitFor(() => {
      expect(api.updateAdminUser).toHaveBeenCalledWith(1, { is_active: true });
      expect(api.updateAdminUser).toHaveBeenCalledWith(2, { is_active: true });
    });
    expect(await screen.findByText("Reactivated 2 users.")).toBeInTheDocument();
  });

  it("bulk-deletes the selection behind a confirm dialog", async () => {
    const users = [mkUser({ id: 1, email: "a@example.com" }), mkUser({ id: 2, email: "b@example.com" })];
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp(users));
    vi.mocked(api.deleteAdminUser).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("a@example.com");

    // Select ONLY id 1, leaving id 2 unselected.
    await user.click(screen.getByLabelText("Select a@example.com"));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    await user.click(within(bar).getByRole("button", { name: "Delete" }));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete permanently" }));

    await waitFor(() => expect(api.deleteAdminUser).toHaveBeenCalledWith(1));
    // The acted-on set is NARROWER than the visible set: the unselected id 2 must
    // never be deleted. (Guards the highest-consequence action in the feature.)
    expect(api.deleteAdminUser).toHaveBeenCalledTimes(1);
    expect(api.deleteAdminUser).not.toHaveBeenCalledWith(2);
    // Singular pluralisation branch ("user", not "users").
    expect(await screen.findByText("Deleted 1 user.")).toBeInTheDocument();
  });

  it("bulk-delete acts on the batch frozen at confirm-open, not a later selection change", async () => {
    const users = [mkUser({ id: 1, email: "a@example.com" }), mkUser({ id: 2, email: "b@example.com" })];
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp(users));
    vi.mocked(api.deleteAdminUser).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("a@example.com");

    // Select only id 1, then open the confirm — this FREEZES the batch as [1].
    await user.click(screen.getByLabelText("Select a@example.com"));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    await user.click(within(bar).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    // Title reflects the frozen count.
    expect(within(dialog).getByText("Delete 1 user?")).toBeInTheDocument();

    // Now ALSO select id 2 while the dialog is open (a live-selection shift).
    // The frozen snapshot must ignore it.
    await user.click(screen.getByLabelText("Select b@example.com"));
    await user.click(within(dialog).getByRole("button", { name: "Delete permanently" }));

    await waitFor(() => expect(api.deleteAdminUser).toHaveBeenCalledWith(1));
    expect(api.deleteAdminUser).toHaveBeenCalledTimes(1);
    expect(api.deleteAdminUser).not.toHaveBeenCalledWith(2);
  });

  it("reports per-user failures and continues the batch PAST the failure", async () => {
    // The FIRST user fails and a LATER user succeeds — so a break-on-first-failure
    // regression (which would skip id 2) is caught by the id-2 assertion below.
    const users = [
      mkUser({ id: 1, email: "solo@example.com", is_admin: true }),
      mkUser({ id: 2, email: "ok@example.com" }),
    ];
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp(users));
    vi.mocked(api.updateAdminUser).mockImplementation((id: number) =>
      id === 1
        ? Promise.reject(new Error("Cannot remove the last active admin."))
        : Promise.resolve(mkUser()),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("solo@example.com");

    await user.click(screen.getByLabelText("Select all users on this page"));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    await user.click(within(bar).getByRole("button", { name: "Deactivate" }));

    // id 2 runs AFTER the failing id 1 — proves the loop did not abort.
    await waitFor(() => expect(api.updateAdminUser).toHaveBeenCalledWith(2, { is_active: false }));
    expect(api.updateAdminUser).toHaveBeenCalledWith(1, { is_active: false });
    // The failing user is named with its reason (amber partial banner).
    expect(await screen.findByText(/1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/solo@example.com: Cannot remove the last active admin/)).toBeInTheDocument();
  });

  it("shows an indeterminate select-all for a partial selection and clears it", async () => {
    const users = [mkUser({ id: 1, email: "a@example.com" }), mkUser({ id: 2, email: "b@example.com" })];
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp(users));
    const user = userEvent.setup();
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("a@example.com");

    const selectAll = screen.getByLabelText("Select all users on this page") as HTMLInputElement;
    // One of two selected → header checkbox is indeterminate, not checked.
    await user.click(screen.getByLabelText("Select a@example.com"));
    expect(selectAll.indeterminate).toBe(true);
    expect(selectAll.checked).toBe(false);
    expect(screen.getByText("1 selected")).toBeInTheDocument();

    // Clear wipes the selection and dismisses the bulk bar.
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    await user.click(within(bar).getByRole("button", { name: "Clear" }));
    expect(screen.queryByRole("region", { name: "Bulk actions" })).not.toBeInTheDocument();
    expect(selectAll.indeterminate).toBe(false);
  });

  it("excludes the acting admin and demo accounts from selection", async () => {
    window.localStorage.setItem("mealbot_user_id", "2"); // acting admin is id 2
    const users = [
      mkUser({ id: 1, email: "a@example.com" }),
      mkUser({ id: 2, email: "me@example.com" }),
      mkUser({ id: 3, email: "demo@example.com", is_demo: true }),
    ];
    vi.mocked(api.fetchAdminUsers).mockResolvedValue(listResp(users));
    renderWithProviders(<UserManagementPanel />);
    await screen.findByText("a@example.com");

    expect(screen.getByLabelText("Select a@example.com")).toBeInTheDocument();
    expect(screen.queryByLabelText("Select me@example.com")).not.toBeInTheDocument(); // self
    expect(screen.queryByLabelText("Select demo@example.com")).not.toBeInTheDocument(); // demo
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
