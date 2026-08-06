import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { CookbookModal } from "./CookbookModal";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { setMobileViewport } from "../test/test-utils";

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

// TEST DATA that collides with a short UI word, not missed translations: the
// shared fixture's meal_type_label is the English "Soup" (the component
// correctly prefers the server's label), and one recipe step reads "Cook with
// curry". Short labels like these are the cost of the 4-character floor — see
// test/i18nAssertions.ts.
const IGNORED_FIXTURE_KEYS = ["mealType.soup", "meal.cook"] as const;

describe("CookbookModal", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it("leaves no untranslated English when switched to Czech, index AND spread", async () => {
    // BOTH viewports: the spread renders a desktop open-book layout and a
    // separate single-column mobile one, each with its own headings. An
    // earlier version of this test only reached one of them — reverting the
    // desktop heading alone did not fail it.
    for (const mobile of [false, true]) {
      setMobileViewport(mobile);
      mockedAuthFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(TWO_RECIPES),
      });
      useLocaleStore.setState({ locale: "cs", explicit: true });

      const { container, unmount } = render(<CookbookModal onClose={() => {}} />, {
        wrapper: createWrapper(),
      });
      const user = userEvent.setup();
      await waitFor(() => screen.getByText("Chicken Curry"));
      expect(untranslatedEnglishIn(container, 4, IGNORED_FIXTURE_KEYS)).toEqual([]);

      await user.click(screen.getByText("Chicken Curry"));
      await waitFor(() => expect(screen.getByText("Suroviny")).toBeInTheDocument());
      expect(untranslatedEnglishIn(container, 4, IGNORED_FIXTURE_KEYS)).toEqual([]);

      unmount();
    }
  });

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

  it("renders a single-column recipe view on mobile (not the open-book spread)", async () => {
    setMobileViewport(true);
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TWO_RECIPES),
    });

    const onClose = vi.fn();
    render(<CookbookModal onClose={onClose} />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await waitFor(() => screen.getByText("Chicken Curry"));
    await user.click(screen.getByText("Chicken Curry"));

    // Mobile header: Back + Close pinned at the top (the ✕ was landing mid-page
    // in the stacked-spread bug). All recipe content flows in one column.
    expect(screen.getByRole("button", { name: /^← back$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /close cookbook/i })).toBeInTheDocument();
    expect(screen.getByText("Chicken Curry")).toBeInTheDocument();
    expect(screen.getByText("Ingredients")).toBeInTheDocument();
    expect(screen.getByText("Steps")).toBeInTheDocument();
    expect(screen.getByText(/chicken breast \(300g\)/)).toBeInTheDocument();
    expect(screen.getByText(/Dice chicken/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove from cookbook/i })).toBeInTheDocument();
    // The desktop spread's "Back to index" label isn't used on mobile.
    expect(screen.queryByText(/back to index/i)).not.toBeInTheDocument();

    // The mobile header handlers actually fire (separate JSX tree from desktop —
    // guard against a future edit silently dropping one). Back → index.
    await user.click(screen.getByRole("button", { name: /^← back$/i }));
    expect(screen.getByPlaceholderText(/Search recipes/)).toBeInTheDocument();
    // Re-open and Close → onClose.
    await user.click(screen.getByText("Chicken Curry"));
    await user.click(screen.getByRole("button", { name: /close cookbook/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
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
