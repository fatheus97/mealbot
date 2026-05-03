import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { CookbookModal } from "./CookbookModal";

vi.mock("../api", () => ({
  authFetch: vi.fn(),
}));

import { authFetch } from "../api";

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const TWO_RECIPES = {
  total: 2,
  items: [
    {
      meal_entry_id: 1,
      name: "Chicken Curry",
      meal_type: "main_course",
      meal_type_label: "Main Course",
      total_time_minutes: 35,
      ingredients: [
        { name: "chicken breast", quantity_grams: 300, is_spice: false },
        { name: "curry powder", quantity_grams: 5, is_spice: true },
      ],
      steps: ["Dice chicken", "Cook with curry"],
      created_at: "2026-04-01T10:00:00Z",
      cooked_at: null,
    },
    {
      meal_entry_id: 2,
      name: "Tomato Soup",
      meal_type: "soup",
      meal_type_label: "Soup",
      total_time_minutes: 20,
      ingredients: [{ name: "tomato", quantity_grams: 400, is_spice: false }],
      steps: ["Simmer", "Blend"],
      created_at: "2026-04-02T10:00:00Z",
      cooked_at: null,
    },
  ],
};

beforeEach(() => {
  mockedAuthFetch.mockReset();
});

describe("CookbookModal", () => {
  it("renders the index with grouped recipes", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TWO_RECIPES),
    });

    render(<CookbookModal onClose={() => {}} />, { wrapper: createWrapper() });

    await waitFor(() => screen.getByText("Chicken Curry"));
    expect(screen.getByText("Tomato Soup")).toBeInTheDocument();
    expect(screen.getByText("Main Course")).toBeInTheDocument();
    expect(screen.getByText("Soup")).toBeInTheDocument();
  });

  it("opens a recipe spread on click and shows ingredients + steps", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TWO_RECIPES),
    });

    render(<CookbookModal onClose={() => {}} />, { wrapper: createWrapper() });
    const user = userEvent.setup();

    await waitFor(() => screen.getByText("Chicken Curry"));
    await user.click(screen.getByText("Chicken Curry"));

    expect(screen.getByText("Ingredients")).toBeInTheDocument();
    expect(screen.getByText("Steps")).toBeInTheDocument();
    expect(screen.getByText(/Dice chicken/)).toBeInTheDocument();
    expect(screen.getByText(/chicken breast \(300g\)/)).toBeInTheDocument();
  });

  it("returns to the index from the spread via Back", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TWO_RECIPES),
    });

    render(<CookbookModal onClose={() => {}} />, { wrapper: createWrapper() });
    const user = userEvent.setup();

    await waitFor(() => screen.getByText("Chicken Curry"));
    await user.click(screen.getByText("Chicken Curry"));
    await waitFor(() => screen.getByText("Ingredients"));

    // The two-stage open animation gates ink controls behind
    // pointer-events: none until ~320ms post-mount; wait for the Back
    // button to become interactive before clicking.
    const backButton = screen.getByText(/Back to index/);
    await waitFor(
      () => {
        if (getComputedStyle(backButton).pointerEvents === "none") {
          throw new Error("Back button still gated");
        }
      },
      { timeout: 1000 },
    );

    await user.click(backButton);
    // Search bar (only present on the index) returns
    expect(screen.getByPlaceholderText(/Search recipes/)).toBeInTheDocument();
  });

  it("renders empty-state copy when the cookbook is empty", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ total: 0, items: [] }),
    });

    render(<CookbookModal onClose={() => {}} />, { wrapper: createWrapper() });

    await waitFor(() => screen.getByText(/Your cookbook is empty/));
    expect(screen.getByText(/Star a recipe in the planner/)).toBeInTheDocument();
  });

  it("opens a confirm dialog from the index ✕ and only deletes after confirm", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TWO_RECIPES),
    });

    render(<CookbookModal onClose={() => {}} />, { wrapper: createWrapper() });
    const user = userEvent.setup();

    await waitFor(() => screen.getByText("Chicken Curry"));
    await user.click(screen.getByLabelText("Remove Chicken Curry from cookbook"));

    // CookbookModal is itself role="dialog"; query by the confirm title's id
    // to disambiguate. No DELETE call yet.
    const confirmDialog = await screen.findByRole("dialog", { name: /Remove from cookbook/i });
    expect(within(confirmDialog).getByText(/Remove "Chicken Curry"/)).toBeInTheDocument();
    expect(mockedAuthFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("/cookbook/"),
      expect.objectContaining({ method: "DELETE" }),
    );

    // Confirm — the dialog's confirm button is labelled "Remove".
    await user.click(within(confirmDialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith(
        "/cookbook/1",
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });

  it("cancels removal and leaves the cookbook untouched", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TWO_RECIPES),
    });

    render(<CookbookModal onClose={() => {}} />, { wrapper: createWrapper() });
    const user = userEvent.setup();

    await waitFor(() => screen.getByText("Chicken Curry"));
    await user.click(screen.getByLabelText("Remove Chicken Curry from cookbook"));

    const confirmDialog = await screen.findByRole("dialog", { name: /Remove from cookbook/i });
    await user.click(within(confirmDialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog", { name: /Remove from cookbook/i })).not.toBeInTheDocument();
    expect(mockedAuthFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("/cookbook/"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("Escape inside the confirm dialog cancels the dialog only, not the cookbook", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TWO_RECIPES),
    });
    const onClose = vi.fn();
    render(<CookbookModal onClose={onClose} />, { wrapper: createWrapper() });
    const user = userEvent.setup();

    await waitFor(() => screen.getByText("Chicken Curry"));
    await user.click(screen.getByLabelText("Remove Chicken Curry from cookbook"));
    await screen.findByRole("dialog", { name: /Remove from cookbook/i });

    await user.keyboard("{Escape}");

    // Confirm dialog is gone, but the cookbook itself stayed open.
    expect(screen.queryByRole("dialog", { name: /Remove from cookbook/i })).not.toBeInTheDocument();
    expect(screen.getByText("Chicken Curry")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("invokes onClose when the close button is clicked", async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ total: 0, items: [] }),
    });
    const onClose = vi.fn();
    render(<CookbookModal onClose={onClose} />, { wrapper: createWrapper() });
    const user = userEvent.setup();

    await waitFor(() => screen.getByText(/Cookbook/));
    await user.click(screen.getByLabelText("Close cookbook"));
    expect(onClose).toHaveBeenCalled();
  });
});
