import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { CalendarFab } from "./CalendarFab";
import { AuthProvider } from "../contexts/AuthContext";

vi.mock("../api", () => ({
  authFetch: vi.fn(),
  fetchPlan: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch } from "../api";

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const okJson = (b: unknown) => ({ ok: true, status: 200, json: () => Promise.resolve(b) });

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

beforeEach(() => {
  localStorage.clear();
  mockedAuthFetch.mockReset();
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url.startsWith("/plan/calendar")) return Promise.resolve(okJson({ plans: [] }));
    if (url === "/plan") return Promise.resolve(okJson([]));
    return Promise.resolve(okJson({}));
  });
});

describe("CalendarFab", () => {
  it("renders nothing when logged out", () => {
    const { container } = render(<CalendarFab onOpenPlan={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    expect(container.innerHTML).toBe("");
  });

  it("opens the calendar modal when clicked", async () => {
    loginUser();
    const user = userEvent.setup();
    render(<CalendarFab onOpenPlan={vi.fn()} />, { wrapper: createWrapper() });

    await user.click(screen.getByRole("button", { name: /open calendar/i }));
    expect(
      await screen.findByRole("dialog", { name: /plan calendar/i }),
    ).toBeInTheDocument();
  });
});
