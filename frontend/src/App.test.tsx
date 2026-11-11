import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ReactNode } from "react";

// Control the auth state directly (no full provider); reassigned per test.
let mockAuth: {
  userId: number | null;
  isAdmin: boolean;
  onboardingCompleted: boolean;
  isDemo: boolean;
};

vi.mock("./contexts/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => mockAuth,
}));

// Stub the heavy authenticated-shell children so AuthRoot renders in isolation.
vi.mock("./components/AuthBar", () => ({ AuthBar: () => <div /> }));
vi.mock("./components/DemoBanner", () => ({ DemoBanner: () => null }));
vi.mock("./components/Fridge", () => ({ Fridge: () => <div /> }));
vi.mock("./components/PlanCatalog", () => ({ PlanCatalog: () => <div /> }));
vi.mock("./components/MealPlanner", () => ({ MealPlanner: () => <div /> }));
vi.mock("./components/OnboardingModal", () => ({ OnboardingModal: () => <div /> }));
vi.mock("./components/CookbookFab", () => ({ CookbookFab: () => <div /> }));
// RestockPrompt reads react-query; the stub shows what MainLayout hands it.
vi.mock("./components/RestockPrompt", () => ({
  RestockPrompt: (p: { restockOpen: boolean; onStartRestock: () => void }) => (
    <button onClick={p.onStartRestock}>{p.restockOpen ? "PROMPT_SUSPENDED" : "PROMPT_LIVE"}</button>
  ),
}));
vi.mock("./components/RestockDialog", () => ({
  RestockDialog: ({ onClose }: { onClose: () => void }) => (
    <button onClick={onClose}>RESTOCK_DIALOG</button>
  ),
}));
vi.mock("./components/admin/AdminDashboard", () => ({
  AdminDashboard: ({ onExit }: { onExit: () => void }) => (
    <div>
      <span>ADMIN_DASHBOARD</span>
      <button onClick={onExit}>stub-back</button>
    </div>
  ),
}));

import App from "./App";

beforeEach(() => {
  mockAuth = { userId: 1, isAdmin: false, onboardingCompleted: true, isDemo: false };
});

describe("App admin gating (AuthRoot)", () => {
  it("hides the Admin button for a non-admin", () => {
    mockAuth = { userId: 1, isAdmin: false, onboardingCompleted: true, isDemo: false };
    render(<App />);
    expect(screen.queryByRole("button", { name: /admin/i })).not.toBeInTheDocument();
    expect(screen.queryByText("ADMIN_DASHBOARD")).not.toBeInTheDocument();
  });

  it("shows the Admin button for an admin and toggles into/out of the dashboard", () => {
    mockAuth = { userId: 1, isAdmin: true, onboardingCompleted: true, isDemo: false };
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /admin/i }));
    expect(screen.getByText("ADMIN_DASHBOARD")).toBeInTheDocument();

    fireEvent.click(screen.getByText("stub-back"));
    expect(screen.queryByText("ADMIN_DASHBOARD")).not.toBeInTheDocument();
  });

  it("resets to main view when the active user changes while in the admin view", () => {
    // Regression guard for the fix: view is not keyed to userId, so without the
    // reset a force-logout in the admin view would drop the next admin straight
    // onto the dashboard.
    mockAuth = { userId: 1, isAdmin: true, onboardingCompleted: true, isDemo: false };
    const { rerender } = render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /admin/i }));
    expect(screen.getByText("ADMIN_DASHBOARD")).toBeInTheDocument();

    // A different admin becomes the active user.
    mockAuth = { userId: 2, isAdmin: true, onboardingCompleted: true, isDemo: false };
    rerender(<App />);

    // Must land on main, not straight onto the dashboard.
    expect(screen.queryByText("ADMIN_DASHBOARD")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /admin/i })).toBeInTheDocument();
  });
});

describe("MainLayout restock wiring", () => {
  it("suspends the prompt while the dialog it opened is open, and resumes after", () => {
    render(<App />);
    fireEvent.click(screen.getByText("PROMPT_LIVE"));
    expect(screen.getByText("RESTOCK_DIALOG")).toBeInTheDocument();
    expect(screen.getByText("PROMPT_SUSPENDED")).toBeInTheDocument();

    fireEvent.click(screen.getByText("RESTOCK_DIALOG"));
    expect(screen.queryByText("RESTOCK_DIALOG")).not.toBeInTheDocument();
    expect(screen.getByText("PROMPT_LIVE")).toBeInTheDocument();
  });
});
