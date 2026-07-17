import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PlanCalendar } from "./PlanCalendar";
import { AuthProvider } from "../contexts/AuthContext";
import { setMobileViewport } from "../test/test-utils";

vi.mock("../api", () => ({
  authFetch: vi.fn(),
  fetchPlan: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch, fetchPlan } from "../api";

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedFetchPlan = fetchPlan as ReturnType<typeof vi.fn>;

const okJson = (body: unknown) => ({
  ok: true,
  status: 200,
  json: () => Promise.resolve(body),
});

const CALENDAR = {
  plans: [
    {
      plan_id: 5,
      start_date: "2026-08-10",
      status: "planned",
      days: [
        { date: "2026-08-10", day_index: 1, meals: ["Chicken Curry"] },
        { date: "2026-08-11", day_index: 2, meals: ["Tomato Soup"] },
      ],
    },
  ],
};

const PLAN_LIST = [
  {
    id: 5,
    created_at: "2026-08-01T00:00:00Z",
    days: 2,
    meals_per_day: 1,
    people_count: 2,
    start_date: "2026-08-10",
    status: "planned",
    total_meals: 2,
    cooked_meals: 0,
    finished_at: null,
  },
];

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
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

function routeDefault(calendar: unknown = CALENDAR) {
  mockedAuthFetch.mockImplementation((url: string, opts?: { method?: string }) => {
    if (url === "/config") return Promise.resolve(okJson({}));
    if (url.startsWith("/plan/calendar")) return Promise.resolve(okJson(calendar));
    if (url === "/plan") return Promise.resolve(okJson(PLAN_LIST));
    if (opts?.method === "PATCH")
      return Promise.resolve(okJson({ plan_id: 5, start_date: "2026-08-20" }));
    return Promise.resolve(okJson({}));
  });
}

beforeEach(() => {
  localStorage.clear();
  mockedAuthFetch.mockReset();
  mockedFetchPlan.mockReset();
});

describe("PlanCalendar", () => {
  it("lists scheduled plans with their meals", async () => {
    loginUser();
    routeDefault();
    render(<PlanCalendar onClose={vi.fn()} onOpenPlan={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    await waitFor(() =>
      expect(screen.getByText(/Chicken Curry/)).toBeInTheDocument(),
    );
    // The window month nav is present.
    expect(screen.getByRole("button", { name: /next month/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous month/i })).toBeInTheDocument();
  });

  it("shows an empty state when nothing is scheduled", async () => {
    loginUser();
    routeDefault({ plans: [] });
    render(<PlanCalendar onClose={vi.fn()} onOpenPlan={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    await waitFor(() =>
      expect(screen.getByText(/No scheduled plans/i)).toBeInTheDocument(),
    );
  });

  it("opens a plan (fetch + onOpenPlan + onClose) when its entry is clicked", async () => {
    loginUser();
    routeDefault();
    mockedFetchPlan.mockResolvedValue({
      plan_id: 5,
      start_date: "2026-08-10",
      days: [],
      shopping_list: [],
    });
    const onOpenPlan = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<PlanCalendar onClose={onClose} onOpenPlan={onOpenPlan} />, {
      wrapper: createWrapper(),
    });

    await screen.findByText(/Chicken Curry/);
    await user.click(screen.getByRole("button", { name: /^open/i }));

    await waitFor(() => expect(mockedFetchPlan).toHaveBeenCalledWith(5));
    expect(onOpenPlan).toHaveBeenCalledWith(
      expect.objectContaining({ plan_id: 5 }),
      expect.objectContaining({ id: 5 }),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("reschedules a plan via the date input (PATCH)", async () => {
    loginUser();
    routeDefault();
    render(<PlanCalendar onClose={vi.fn()} onOpenPlan={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    const input = await screen.findByLabelText(/reschedule plan 5/i);
    fireEvent.change(input, { target: { value: "2026-08-20" } });

    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith("/plan/5", {
        method: "PATCH",
        body: JSON.stringify({ start_date: "2026-08-20" }),
      }),
    );
  });

  it("surfaces a reschedule failure instead of failing silently", async () => {
    loginUser();
    mockedAuthFetch.mockImplementation((url: string, opts?: { method?: string }) => {
      if (url === "/config") return Promise.resolve(okJson({}));
      if (url.startsWith("/plan/calendar")) return Promise.resolve(okJson(CALENDAR));
      if (url === "/plan") return Promise.resolve(okJson(PLAN_LIST));
      if (opts?.method === "PATCH")
        return Promise.resolve({ ok: false, status: 429, json: () => Promise.resolve({}) });
      return Promise.resolve(okJson({}));
    });
    render(<PlanCalendar onClose={vi.fn()} onOpenPlan={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    const input = await screen.findByLabelText(/reschedule plan 5/i);
    fireEvent.change(input, { target: { value: "2026-08-20" } });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/Couldn't reschedule/i),
    );
  });

  it("hides the weekday grid on mobile (agenda fallback) but keeps the list", async () => {
    setMobileViewport(true);
    loginUser();
    routeDefault();
    render(<PlanCalendar onClose={vi.fn()} onOpenPlan={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    await waitFor(() =>
      expect(screen.getByText(/Chicken Curry/)).toBeInTheDocument(),
    );
    // The desktop 7-column weekday header row is not rendered on mobile.
    expect(screen.queryByText("Sun")).not.toBeInTheDocument();
  });

  it("navigates months (the label changes on Next)", async () => {
    loginUser();
    routeDefault();
    render(<PlanCalendar onClose={vi.fn()} onOpenPlan={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    await screen.findByText(/Chicken Curry/);

    // Capture the current month label, click Next, assert it changed.
    const nextBtn = screen.getByRole("button", { name: /next month/i });
    const before = nextBtn.parentElement?.querySelector("strong")?.textContent;
    const user = userEvent.setup();
    await user.click(nextBtn);
    const after = nextBtn.parentElement?.querySelector("strong")?.textContent;
    expect(after).not.toBe(before);
  });
});
