import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { AdminDashboard } from "./AdminDashboard";
import * as api from "../../api";
import type {
  ActivityStatsResponse,
  FunnelStatsResponse,
  OverviewStats,
  RevenueStats,
  UsageByUserResponse,
  UsageStatsResponse,
} from "../../types";

vi.mock("../../api", () => ({
  // AuthProvider calls authFetch("/config") on mount — stub it so no real fetch.
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  fetchAdminOverview: vi.fn(),
  fetchAdminUsage: vi.fn(),
  fetchAdminUsageByUser: vi.fn(),
  fetchAdminActivity: vi.fn(),
  fetchAdminRevenue: vi.fn(),
  fetchAdminFunnel: vi.fn(),
}));

const OVERVIEW: OverviewStats = {
  total_users: 5,
  active_users_30d: 3,
  demo_users: 2,
  admin_users: 1,
  llm_calls: 42,
  prompt_tokens: 100,
  completion_tokens: 50,
  total_tokens: 900,
  generations_by_surface: [{ surface: "meal_plan", count: 10 }],
};

const USAGE: UsageStatsResponse = {
  from_date: "2026-06-12",
  to_date: "2026-07-12",
  granularity: "day",
  series: [
    { period: "2026-07-11", calls: 2, prompt_tokens: 10, completion_tokens: 5, total_tokens: 100 },
    { period: "2026-07-12", calls: 3, prompt_tokens: 20, completion_tokens: 10, total_tokens: 200 },
  ],
  by_surface: [{ surface: "meal_plan", calls: 5, total_tokens: 300 }],
  by_provider: [{ provider: "gemini", calls: 5, total_tokens: 300 }],
};

const BY_USER: UsageByUserResponse = {
  users_with_usage: 2,
  avg_tokens_per_user: 150,
  top_users: [
    { user_id: 1, email: "alice@example.com", calls: 3, total_tokens: 200, avg_tokens_per_call: 66.7 },
  ],
};

const ACTIVITY: ActivityStatsResponse = {
  from_date: "2026-06-12",
  to_date: "2026-07-12",
  granularity: "day",
  series: [{ period: "2026-07-12", generations: 4 }],
  by_surface: [{ surface: "meal_plan", count: 4 }],
};

const REVENUE: RevenueStats = {
  currency: "eur",
  total_cents: 0,
  sales_count: 0,
  eu_cross_border_b2c_cents: 0,
  cz_domestic_cents: 0,
  non_eur_sales_count: 0,
  eur_czk_rate: 25,
  thresholds: [],
  by_country: [],
  recent: [],
};

const FUNNEL: FunnelStatsResponse = {
  stages: [
    { key: "signed_up", label: "Signed up", count: 5 },
    { key: "generated", label: "Generated a recipe", count: 3 },
    { key: "confirmed", label: "Confirmed a plan", count: 2 },
    { key: "cooked", label: "Cooked a meal", count: 1 },
    { key: "paid", label: "Subscribed", count: 1 },
  ],
  by_source: [{ source: "direct", signed_up: 5, generated: 3, confirmed: 2, cooked: 1, paid: 1 }],
};

beforeEach(() => {
  vi.clearAllMocks(); // reset call history between tests (keeps implementations)
  window.localStorage.clear();
  vi.mocked(api.fetchAdminOverview).mockResolvedValue(OVERVIEW);
  vi.mocked(api.fetchAdminUsage).mockResolvedValue(USAGE);
  vi.mocked(api.fetchAdminUsageByUser).mockResolvedValue(BY_USER);
  vi.mocked(api.fetchAdminActivity).mockResolvedValue(ACTIVITY);
  vi.mocked(api.fetchAdminRevenue).mockResolvedValue(REVENUE);
  vi.mocked(api.fetchAdminFunnel).mockResolvedValue(FUNNEL);
});

describe("AdminDashboard", () => {
  it("renders Overview metrics by default for an admin", async () => {
    window.localStorage.setItem("mealbot_is_admin", "true");
    renderWithProviders(<AdminDashboard onExit={() => {}} />);

    expect(screen.getByText("🛠️ Admin Dashboard")).toBeInTheDocument();
    // Overview is the default tab: total_tokens (900) from the overview card.
    expect(await screen.findByText("900")).toBeInTheDocument();
    // The Overview tab is marked selected; the others are not.
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Generation" })).toHaveAttribute("aria-selected", "false");
    // The top-users table lives on the Generation tab, so it isn't in the DOM yet.
    expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument();
  });

  it("switches to the Generation tab to reveal the top-user table", async () => {
    window.localStorage.setItem("mealbot_is_admin", "true");
    const user = userEvent.setup();
    renderWithProviders(<AdminDashboard onExit={() => {}} />);

    // Wait for the default tab to settle, then switch.
    await screen.findByText("900");
    await user.click(screen.getByRole("tab", { name: "Generation" }));

    expect(screen.getByRole("tab", { name: "Generation" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
  });

  it("switches to the Revenue tab", async () => {
    window.localStorage.setItem("mealbot_is_admin", "true");
    const user = userEvent.setup();
    renderWithProviders(<AdminDashboard onExit={() => {}} />);

    await screen.findByText("900");
    await user.click(screen.getByRole("tab", { name: "Revenue" }));

    // The REVENUE fixture has no sales → the panel's empty state.
    expect(await screen.findByText(/no sales recorded yet/i)).toBeInTheDocument();
  });

  it("blocks a non-admin and never calls the admin endpoints", () => {
    // mealbot_is_admin not set → isAdmin false
    renderWithProviders(<AdminDashboard onExit={() => {}} />);

    expect(screen.getByText(/don't have access/i)).toBeInTheDocument();
    expect(api.fetchAdminOverview).not.toHaveBeenCalled();
    // No tabs render on the no-access screen.
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });
});
