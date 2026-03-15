import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PlanCatalog } from "./PlanCatalog";
import { AuthProvider } from "../contexts/AuthContext";
import type { ReactNode } from "react";
import type { MealPlanSummary } from "../types";

vi.mock("../api", () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch } from "../api";

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

function loginUser() {
  localStorage.setItem("mealbot_token", "test-token");
  localStorage.setItem("mealbot_user_id", "1");
  localStorage.setItem("mealbot_user_email", "test@test.com");
}

const SAMPLE_PLAN: MealPlanSummary = {
  id: 1,
  created_at: "2026-03-10T12:00:00Z",
  days: 2,
  meals_per_day: 3,
  people_count: 2,
  status: "planned",
  total_meals: 6,
  cooked_meals: 0,
  finished_at: null,
};

beforeEach(() => {
  vi.stubGlobal("alert", vi.fn());
});

describe("PlanCatalog", () => {
  it("returns null when logged out", () => {
    const { container } = render(
      <PlanCatalog onOpenPlan={vi.fn()} />,
      { wrapper: createWrapper() },
    );
    expect(container.innerHTML).toBe("");
  });

  it("shows empty state when no plans", async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([]),
    });

    render(<PlanCatalog onOpenPlan={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/no plans yet/i)).toBeInTheDocument();
    });
  });

  it("renders plan summaries with status badges", async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([SAMPLE_PLAN]),
    });

    render(<PlanCatalog onOpenPlan={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/2d \/ 3 meals \/ 2p/)).toBeInTheDocument();
      expect(screen.getByText(/planned \(0\/6\)/)).toBeInTheDocument();
    });
  });

  it("calls onOpenPlan when Open button clicked", async () => {
    loginUser();
    const onOpenPlan = vi.fn();

    // First call: list plans
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([SAMPLE_PLAN]),
    });

    render(<PlanCatalog onOpenPlan={onOpenPlan} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Open")).toBeInTheDocument();
    });

    // Second call: load plan detail
    const planDetail = { plan_id: 1, days: [], shopping_list: [] };
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(planDetail),
    });

    const user = userEvent.setup();
    await user.click(screen.getByText("Open"));

    await waitFor(() => {
      expect(onOpenPlan).toHaveBeenCalledWith(planDetail, SAMPLE_PLAN);
    });
  });

  it("shows delete confirmation on Delete click", async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([SAMPLE_PLAN]),
    });

    render(<PlanCatalog onOpenPlan={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Delete")).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByText("Delete"));

    expect(screen.getByText("Confirm")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("cancels delete on Cancel click", async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([SAMPLE_PLAN]),
    });

    render(<PlanCatalog onOpenPlan={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Delete")).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByText("Delete"));
    await user.click(screen.getByText("Cancel"));

    expect(screen.queryByText("Confirm")).not.toBeInTheDocument();
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });
});
