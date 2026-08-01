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


/**
 * Fixture dates in the month AFTER today, as YYYY-MM-DD.
 *
 * These used to hardcode a fixed August-2026 start. The calendar opens on the
 * CURRENT month, so while today was earlier than that the plan rendered only in
 * the agenda list and the /Chicken Curry/ assertions matched exactly one node.
 * The moment the real clock reached that month the same plan ALSO rendered in
 * the month grid, two nodes matched, and three tests began failing in a file
 * nobody had touched — a time bomb that fires on a date, not on a change.
 *
 * Deriving from today keeps the plan outside the default grid, so the
 * assertions stay single-match whenever the suite runs. Chosen over
 * vi.setSystemTime, which needs fake timers and would fight userEvent/waitFor
 * in this file.
 *
 * ⚠️ THE DAY MUST BE 15 OR LATER. monthMatrix() always emits a 6x7 = 42-cell
 * grid rewound to the week's Sunday, and PlanCalendar renders a chip for EVERY
 * cell — `inMonth` only changes styling, not whether the meal name is in the
 * DOM. So the current month's grid spills into next month by
 *
 *     42 - weekday(1st, 0=Sun) - daysInMonth
 *
 * which peaks at 42 - 0 - 28 = 14 (a 28-day February beginning on a Sunday).
 * Days 1-14 of next month can therefore land in a rendered cell and make the
 * /Chicken Curry/ assertions multi-match again — the same failure this helper
 * exists to prevent, re-triggered by calendar SHAPE instead of a literal.
 * Day 15+ is the only month-shape-independent safe zone; 20/21 leaves margin.
 */
function nextMonthDay(day: number): string {
  const now = new Date();
  // Day 1 of next month, then set the day — never overflows (no 31 Feb).
  const d = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  d.setDate(day);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

const PLAN_START = nextMonthDay(20);
const PLAN_DAY2 = nextMonthDay(21);

const CALENDAR = {
  plans: [
    {
      plan_id: 5,
      start_date: PLAN_START,
      status: "planned",
      days: [
        // CalendarMeal objects, not name strings. Day 2 is leftovers of day 1
        // so every render path (grid chip, agenda, title) is exercised.
        {
          date: PLAN_START,
          day_index: 1,
          meals: [
            {
              name: "Chicken Curry",
              is_leftover: false,
              source_date: null,
              source_name: null,
            },
          ],
        },
        {
          date: PLAN_DAY2,
          day_index: 2,
          meals: [
            {
              name: "Tomato Soup",
              is_leftover: false,
              source_date: null,
              source_name: null,
            },
            // Same-day leftover of the soup (valid: an earlier slot the same
            // day). Deliberately NOT "Leftovers: Chicken Curry" — that would
            // also match the existing /Chicken Curry/ assertions and make them
            // ambiguous, which is a fixture problem, not a real one.
            {
              name: "Leftovers: Tomato Soup",
              is_leftover: true,
              source_date: PLAN_DAY2,
              source_name: "Tomato Soup",
            },
          ],
        },
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
    start_date: PLAN_START,
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
      start_date: PLAN_START,
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

describe("fixture-date invariant", () => {
  it("keeps the fixture past the grid's maximum spill into next month", () => {
    // monthMatrix() emits a fixed 6x7 grid rewound to Sunday, and every cell
    // renders its chips, so the current month can show up to
    //   42 - weekday(1st) - daysInMonth
    // days of the NEXT month — peaking at 42 - 0 - 28 = 14. A fixture on day
    // 1..14 can therefore appear in the default grid AND the agenda list, which
    // is exactly the multi-match failure this file was fixed for. Guard the
    // invariant rather than trusting a comment.
    const MAX_SPILL = 14;
    for (const iso of [PLAN_START, PLAN_DAY2]) {
      expect(Number(iso.slice(-2))).toBeGreaterThan(MAX_SPILL);
    }
  });

  it("worst-case month shape really does spill 14 days", () => {
    // Proves MAX_SPILL above rather than asserting it from memory: February in
    // a non-leap year starting on a Sunday is the extreme.
    let worst = 0;
    for (let year = 2026; year < 2046; year++) {
      for (let month = 0; month < 12; month++) {
        const first = new Date(year, month, 1);
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        worst = Math.max(worst, 42 - first.getDay() - daysInMonth);
      }
    }
    expect(worst).toBe(14);
  });
});
