import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../../test/test-utils";
import { AdminDashboard } from "./AdminDashboard";
import * as api from "../../api";
import type {
  ActivityStatsResponse,
  OverviewStats,
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

beforeEach(() => {
  vi.clearAllMocks(); // reset call history between tests (keeps implementations)
  window.localStorage.clear();
  vi.mocked(api.fetchAdminOverview).mockResolvedValue(OVERVIEW);
  vi.mocked(api.fetchAdminUsage).mockResolvedValue(USAGE);
  vi.mocked(api.fetchAdminUsageByUser).mockResolvedValue(BY_USER);
  vi.mocked(api.fetchAdminActivity).mockResolvedValue(ACTIVITY);
});

describe("AdminDashboard", () => {
  it("renders metrics and the top-user table for an admin", async () => {
    window.localStorage.setItem("mealbot_is_admin", "true");
    renderWithProviders(<AdminDashboard onExit={() => {}} />);

    expect(screen.getByText("🛠️ Admin Dashboard")).toBeInTheDocument();
    // total_tokens (900) from the overview card
    expect(await screen.findByText("900")).toBeInTheDocument();
    // top-user row from the by-user query
    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
  });

  it("blocks a non-admin and never calls the admin endpoints", () => {
    // mealbot_is_admin not set → isAdmin false
    renderWithProviders(<AdminDashboard onExit={() => {}} />);

    expect(screen.getByText(/don't have access/i)).toBeInTheDocument();
    expect(api.fetchAdminOverview).not.toHaveBeenCalled();
  });
});
