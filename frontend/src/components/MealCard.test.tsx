import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MealCard } from "./MealCard";
import type { MealEntrySummary, PlannedMeal } from "../types";

// MealCard is purely presentational — no hooks, no react-query, no auth — so it
// renders bare. These tests pin the affordance-gating matrix (which button shows
// up in which plan state), because that branching is what actually carries risk:
// it was ~150 lines of nested ternaries inline in MealPlanner before extraction.

const MEAL: PlannedMeal = {
  name: "Chicken curry",
  meal_type: "hot_dinner",
  meal_type_label: "Hot dinner",
  ingredients: [{ name: "chicken", quantity_grams: 400 }],
  steps: ["Brown the chicken", "Add sauce"],
  total_time_minutes: 35,
};

const ENTRY: MealEntrySummary = {
  id: 7,
  day_index: 1,
  meal_index: 1,
  name: "Chicken curry",
  meal_type: "hot_dinner",
  cooked_at: null,
  is_favorite: false,
};

function renderCard(overrides: Partial<React.ComponentProps<typeof MealCard>> = {}) {
  const props: React.ComponentProps<typeof MealCard> = {
    meal: MEAL,
    entry: null,
    isFrozen: false,
    isCooked: false,
    isEditing: false,
    isCooking: false,
    isConfirmed: false,
    isFinished: false,
    cookStorageKey: "cookmode:1:0:0",
    cookTogglePending: false,
    cookPending: false,
    favoritePending: false,
    savePending: false,
    saveError: null,
    cookFailed: false,
    onToggleFreeze: vi.fn(),
    onCookToggle: vi.fn(),
    onStartEdit: vi.fn(),
    onCancelEdit: vi.fn(),
    onSave: vi.fn(),
    onStartCooking: vi.fn(),
    onStopCooking: vi.fn(),
    onFinishCooking: vi.fn(),
    onFavoriteToggle: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<MealCard {...props} />) };
}

describe("MealCard", () => {
  it("renders the meal type, name and total time", () => {
    renderCard();
    expect(screen.getByText(/HOT DINNER/)).toBeInTheDocument();
    expect(screen.getByText(/Chicken curry/)).toBeInTheDocument();
    expect(screen.getByLabelText("Total time 35 minutes")).toBeInTheDocument();
  });

  it("omits the time when the meal has none", () => {
    renderCard({ meal: { ...MEAL, total_time_minutes: null } });
    expect(screen.queryByLabelText(/Total time/)).not.toBeInTheDocument();
  });

  describe("pre-confirm", () => {
    it("offers Freeze and not Cook", () => {
      renderCard();
      expect(screen.getByRole("button", { name: /Freeze/ })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Cook$/ })).not.toBeInTheDocument();
    });

    it("reads Frozen and fires onToggleFreeze when clicked", async () => {
      const { props } = renderCard({ isFrozen: true });
      const btn = screen.getByRole("button", { name: /Frozen/ });
      await userEvent.click(btn);
      expect(props.onToggleFreeze).toHaveBeenCalledOnce();
    });

    it("shows no favorite star without a persisted entry", () => {
      renderCard();
      expect(screen.queryByRole("button", { name: /favorite/i })).not.toBeInTheDocument();
    });
  });

  describe("confirmed", () => {
    it("swaps Freeze for Cook and shows the favorite star", () => {
      renderCard({ isConfirmed: true, entry: ENTRY });
      expect(screen.queryByRole("button", { name: /Freeze/ })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^Cook$/ })).toBeInTheDocument();
    });

    it("disables the cook toggle while either direction is in flight", () => {
      renderCard({ isConfirmed: true, entry: ENTRY, cookTogglePending: true });
      expect(screen.getByRole("button", { name: /^Cook$/ })).toBeDisabled();
    });

    it("offers Start cooking only when the meal is uncooked and has steps", () => {
      renderCard({ isConfirmed: true, entry: ENTRY });
      expect(screen.getByRole("button", { name: /Start cooking/ })).toBeInTheDocument();
    });

    it("hides Start cooking once cooked", () => {
      renderCard({ isConfirmed: true, entry: { ...ENTRY, cooked_at: "2026-07-19T10:00:00Z" }, isCooked: true });
      expect(screen.queryByRole("button", { name: /Start cooking/ })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Cooked/ })).toBeInTheDocument();
    });

    it("hides Start cooking for a meal with no steps", () => {
      renderCard({ isConfirmed: true, entry: ENTRY, meal: { ...MEAL, steps: [] } });
      expect(screen.queryByRole("button", { name: /Start cooking/ })).not.toBeInTheDocument();
    });
  });

  describe("finished", () => {
    it("shows a read-only cooked state and no Edit affordance", () => {
      renderCard({ isConfirmed: true, isFinished: true, entry: ENTRY });
      expect(screen.getByText("Not cooked")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Edit$/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Cook$/ })).not.toBeInTheDocument();
    });
  });

  describe("editing", () => {
    it("replaces the ingredients/steps body with the editor", () => {
      renderCard({ isEditing: true });
      // The read-only body is gone...
      expect(screen.queryByText("Ingredients:")).not.toBeInTheDocument();
      // ...and the editor's save control is present.
      expect(screen.getByRole("button", { name: /Save/i })).toBeInTheDocument();
    });

    it("surfaces a save error", () => {
      renderCard({ isEditing: true, saveError: "Save failed" });
      expect(screen.getByText("Save failed")).toBeInTheDocument();
    });

    it("fires onStartEdit from the Edit button", async () => {
      const { props } = renderCard();
      await userEvent.click(screen.getByRole("button", { name: /^Edit$/ }));
      expect(props.onStartEdit).toHaveBeenCalledOnce();
    });
  });

  describe("cooking overlay", () => {
    // Assert on the overlay's own control, not the recipe text: while cooking,
    // the card body still renders the same steps underneath, so a step string
    // matches twice.
    // A single-step meal opens cook mode already on its last step, so the done
    // button renders immediately — which also pins the doneLabel passthrough.
    const ONE_STEP: PlannedMeal = { ...MEAL, steps: ["Reheat"] };

    it("renders CookMode only with an entry", () => {
      renderCard({ isConfirmed: true, isCooking: true, entry: ENTRY, meal: ONE_STEP });
      expect(screen.getByRole("button", { name: "Mark as cooked" })).toBeInTheDocument();
    });

    it("does not render CookMode without an entry", () => {
      renderCard({ isCooking: true, entry: null, meal: ONE_STEP });
      expect(screen.queryByRole("button", { name: "Mark as cooked" })).not.toBeInTheDocument();
    });

    it("shows the overlay's saving state while the cook mutation is in flight", () => {
      renderCard({ isConfirmed: true, isCooking: true, entry: ENTRY, meal: ONE_STEP, cookPending: true });
      expect(screen.getByRole("button", { name: "Saving…" })).toBeInTheDocument();
    });

    // REGRESSION GUARD for the two-prop split. cookTogglePending covers
    // cook-OR-uncook (it disables the Cook/Cooked toggle); cookPending covers
    // cook alone. Cook mode's done button must follow cookPending only, so an
    // unrelated uncook in flight cannot disable it. This test fails if the two
    // props are ever collapsed back into one -- which no other test would catch.
    it("keeps the overlay's done button enabled while an unrelated uncook is in flight", () => {
      renderCard({
        isConfirmed: true,
        isCooking: true,
        entry: ENTRY,
        meal: ONE_STEP,
        cookTogglePending: true,
        cookPending: false,
      });
      expect(screen.getByRole("button", { name: "Mark as cooked" })).toBeEnabled();
    });

    it("surfaces a cook failure inside the overlay", () => {
      renderCard({ isConfirmed: true, isCooking: true, entry: ENTRY, cookFailed: true });
      expect(screen.getByText(/Couldn't mark as cooked/)).toBeInTheDocument();
    });
  });
});


describe("MealCard — leftovers", () => {
  const LEFTOVER: PlannedMeal = {
    name: "Leftovers: Chicken curry",
    meal_type: "light_lunch",
    meal_type_label: "Light lunch",
    ingredients: [],
    steps: ["Reheat the Chicken curry you cooked earlier and serve."],
    total_time_minutes: 15,
    leftover_of: { day_index: 0, meal_index: 0 },
  };

  const SOURCE_LABEL = "Sun Jul 19 · Hot dinner — Chicken curry";

  it("shows the provenance badge with the full label on desktop", () => {
    renderCard({ meal: LEFTOVER, leftoverSource: SOURCE_LABEL, isMobile: false });
    expect(screen.getByText(/Leftovers from Sun Jul 19/)).toBeInTheDocument();
  });

  it("shows the compact badge on mobile with the full label in title", () => {
    renderCard({ meal: LEFTOVER, leftoverSource: SOURCE_LABEL, isMobile: true });
    const badge = screen.getByText("↻ Leftovers");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", `Leftovers from ${SOURCE_LABEL}`);
  });

  it("degrades to the compact badge when the source cannot be resolved", () => {
    // A stale link in a stored plan resolves to null rather than throwing.
    renderCard({ meal: LEFTOVER, leftoverSource: null, isMobile: false });
    expect(screen.getByText("↻ Leftovers")).toBeInTheDocument();
  });

  it("replaces the ingredients list with a provenance line", () => {
    renderCard({ meal: LEFTOVER, leftoverSource: SOURCE_LABEL });
    // An empty "Ingredients:" list would read as a bug — a leftover has none
    // of its own, they were bought with the source.
    expect(screen.queryByText("Ingredients:")).not.toBeInTheDocument();
    expect(screen.getByText(/nothing extra to buy/)).toBeInTheDocument();
  });

  it("hides Freeze — the server freezes link groups atomically", () => {
    renderCard({ meal: LEFTOVER, leftoverSource: SOURCE_LABEL, isConfirmed: false });
    expect(screen.queryByRole("button", { name: /Freeze/ })).not.toBeInTheDocument();
  });

  it("still offers Freeze on an ordinary meal", () => {
    renderCard({ isConfirmed: false });
    expect(screen.getByRole("button", { name: /Freeze/ })).toBeInTheDocument();
  });

  it("hides Start cooking even though the leftover has a step", () => {
    // Gated on isLeftover explicitly, NOT on steps.length: the reheat step
    // would otherwise open cook mode and write progress under
    // cookmode:${planId}:${day}:${meal} for a meal that isn't being cooked.
    renderCard({
      meal: LEFTOVER,
      leftoverSource: SOURCE_LABEL,
      isConfirmed: true,
      entry: ENTRY,
    });
    expect(screen.queryByRole("button", { name: /Start cooking/ })).not.toBeInTheDocument();
    // But it can still be marked cooked — a leftover does get eaten.
    expect(screen.getByRole("button", { name: /^Cook$/ })).toBeInTheDocument();
  });

  it("leaves an ordinary meal's Start cooking intact", () => {
    renderCard({ isConfirmed: true, entry: ENTRY });
    expect(screen.getByRole("button", { name: /Start cooking/ })).toBeInTheDocument();
  });


  describe("cookbook star", () => {
    const LEFTOVER_MEAL: PlannedMeal = {
      name: "Leftovers: Chicken curry",
      meal_type: "light_lunch",
      meal_type_label: "Light lunch",
      ingredients: [],
      steps: ["Reheat the Chicken curry you cooked earlier and serve."],
      leftover_of: { day_index: 0, meal_index: 0 },
    };

    it("disables the star on a leftover and explains why", () => {
      // The backend 422s a favorite on a leftover (it would poison the global
      // RAG corpus with an ingredient-free "recipe"), and useFavoriteMeal has
      // no onError — so an ENABLED star would be a control that silently never
      // works. Every other gated affordance got an explicit !isLeftover; this
      // one was missed.
      renderCard({
        meal: LEFTOVER_MEAL,
        leftoverSource: "Sun Jul 19 · Hot dinner — Chicken curry",
        isConfirmed: true,
        entry: ENTRY,
      });
      const star = screen.getByRole("switch");
      expect(star).toBeDisabled();
      expect(star).toHaveAttribute("title", expect.stringContaining("star the original meal"));
    });

    it("does not fire onFavoriteToggle when the leftover's star is clicked", async () => {
      const { props } = renderCard({
        meal: LEFTOVER_MEAL,
        leftoverSource: "Sun Jul 19 · Hot dinner — Chicken curry",
        isConfirmed: true,
        entry: ENTRY,
      });
      await userEvent.click(screen.getByRole("switch"));
      expect(props.onFavoriteToggle).not.toHaveBeenCalled();
    });

    it("leaves the star enabled on an ordinary meal", async () => {
      const { props } = renderCard({ isConfirmed: true, entry: ENTRY });
      const star = screen.getByRole("switch");
      expect(star).toBeEnabled();
      await userEvent.click(star);
      expect(props.onFavoriteToggle).toHaveBeenCalledOnce();
    });

    it("still disables the star while a favorite mutation is in flight", () => {
      renderCard({ isConfirmed: true, entry: ENTRY, favoritePending: true });
      expect(screen.getByRole("switch")).toBeDisabled();
    });
  });

  it("shows no badge on an ordinary meal", () => {
    renderCard({ leftoverSource: null });
    expect(screen.queryByText(/Leftovers/)).not.toBeInTheDocument();
  });
});
