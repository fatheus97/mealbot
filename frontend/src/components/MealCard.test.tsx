import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MealCard } from "./MealCard";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { CookTimerProvider } from "../contexts/CookTimerContext";
import type { IngredientNutrition, MealEntrySummary, MealNutrition, PlannedMeal, SourceAttribution } from "../types";

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
  // MealCard renders CookMode when `isCooking`, and cooking timers now live in
  // an app-level store, so the provider is part of the component's environment.
  return {
    props,
    ...render(
      <CookTimerProvider>
        <MealCard {...props} />
      </CookTimerProvider>,
    ),
  };
}

describe("MealCard", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it("leaves no untranslated English when switched to Czech", () => {
    // Exact dictionary comparison, not a "looks English" regex — most Czech is
    // ASCII. Only sees what is RENDERED, so the conditional branches below get
    // their own cases (see test/i18nAssertions.ts).
    useLocaleStore.setState({ locale: "cs", explicit: true });
    renderCard();
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });

  it("stays translated in the cooked + frozen + leftover states too", () => {
    // Those labels swap on a ternary, so the default render never shows them —
    // the exact shape that let an English string ship twice in earlier slices.
    useLocaleStore.setState({ locale: "cs", explicit: true });
    renderCard({ isCooked: true, isFrozen: true });
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });

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

    it("shows no cookbook heart without a persisted entry", () => {
      // The heart is a role=switch named "Add to cookbook"; querying a
      // "favorite" BUTTON could never find it, so this used to pass vacuously.
      renderCard();
      expect(screen.queryByRole("switch", { name: /cookbook/i })).not.toBeInTheDocument();
    });
  });

  describe("confirmed", () => {
    it("swaps Freeze for Cook and shows the cookbook heart", () => {
      renderCard({ isConfirmed: true, entry: ENTRY });
      expect(screen.queryByRole("button", { name: /Freeze/ })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^Cook$/ })).toBeInTheDocument();
      expect(screen.getByRole("switch", { name: "Add to cookbook" })).toBeInTheDocument();
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

    it("shows no ingredient-edit hint outside the editor", () => {
      // The claim is true for a plan meal only (Cook Now debits the edited
      // recipe), which is why MealCard supplies it rather than MealEditor.
      renderCard();
      expect(
        screen.queryByRole("button", { name: "About editing ingredients" }),
      ).not.toBeInTheDocument();
    });

    it("opens the ingredient-edit hint beside the editor's Ingredients legend", async () => {
      const user = userEvent.setup();
      renderCard({ isEditing: true });
      await user.click(screen.getByRole("button", { name: "About editing ingredients" }));
      expect(screen.getByRole("tooltip")).toHaveTextContent(
        /don't update the shopping list or what was already taken from your fridge/i,
      );
      // The hint sits inside the <legend>, but must not join the group's name:
      // the fieldset is labelled by the legend text alone, open bubble or not.
      expect(screen.getByRole("group", { name: "Ingredients" })).toBeInTheDocument();
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


  describe("cookbook heart", () => {
    const LEFTOVER_MEAL: PlannedMeal = {
      name: "Leftovers: Chicken curry",
      meal_type: "light_lunch",
      meal_type_label: "Light lunch",
      ingredients: [],
      steps: ["Reheat the Chicken curry you cooked earlier and serve."],
      leftover_of: { day_index: 0, meal_index: 0 },
    };

    it("disables the heart on a leftover and explains why", () => {
      // The backend 422s a favorite on a leftover (it would poison the global
      // RAG corpus with an ingredient-free "recipe"), and useFavoriteMeal has
      // no onError — so an ENABLED heart would be a control that silently never
      // works. Every other gated affordance got an explicit !isLeftover; this
      // one was missed.
      renderCard({
        meal: LEFTOVER_MEAL,
        leftoverSource: "Sun Jul 19 · Hot dinner — Chicken curry",
        isConfirmed: true,
        entry: ENTRY,
      });
      const heart = screen.getByRole("switch");
      expect(heart).toBeDisabled();
      expect(heart).toHaveAttribute("title", expect.stringContaining("Save the original meal"));
    });

    it("does not fire onFavoriteToggle when the leftover's heart is clicked", async () => {
      const { props } = renderCard({
        meal: LEFTOVER_MEAL,
        leftoverSource: "Sun Jul 19 · Hot dinner — Chicken curry",
        isConfirmed: true,
        entry: ENTRY,
      });
      await userEvent.click(screen.getByRole("switch"));
      expect(props.onFavoriteToggle).not.toHaveBeenCalled();
    });

    it("leaves the heart enabled on an ordinary meal", async () => {
      const { props } = renderCard({ isConfirmed: true, entry: ENTRY });
      const heart = screen.getByRole("switch");
      expect(heart).toBeEnabled();
      await userEvent.click(heart);
      expect(props.onFavoriteToggle).toHaveBeenCalledOnce();
    });

    it("still disables the heart while a favorite mutation is in flight", () => {
      renderCard({ isConfirmed: true, entry: ENTRY, favoritePending: true });
      expect(screen.getByRole("switch")).toBeDisabled();
    });
  });

  it("shows no badge on an ordinary meal", () => {
    renderCard({ leftoverSource: null });
    expect(screen.queryByText(/Leftovers/)).not.toBeInTheDocument();
  });
});

// ── Nutrition chip and panel (docs/nutrition-design.md, "What the user sees") ──

const SOURCE: SourceAttribution = {
  name: "Ciqual 2025",
  publisher: "Anses",
  published: "2025-11-19",
  doi: "10.57745/RDMHWY",
};

function ing(over: Partial<IngredientNutrition>): IngredientNutrition {
  return {
    name: "chicken", grams: 400, status: "counted", reason: null, alim_code: 36018,
    source_name: "Chicken, breast, raw", state: "raw", confidence: "A",
    per_100g: { kcal: 121.1, kj: 510.2, protein: 23.4, fat: 2.1, carbohydrate: 0 },
    contribution: { kcal: 484.4, kj: 2040.8, protein: 93.6, fat: 8.4, carbohydrate: 0 },
    ...over,
  };
}

const FIGURE: MealNutrition = {
  day_index: 0,
  meal_index: 0,
  per_serving: { kcal: 1853.4, kj: 7754.6, protein: 42.3, fat: 0.3, carbohydrate: 120.6 },
  withheld_reason: null,
  servings: 4,
  complete: true,
  coverage: 1,
  ingredients: [
    ing({}),
    ing({
      name: "water", grams: 200, status: "water", alim_code: null, source_name: null,
      state: null, confidence: null, per_100g: null, contribution: null,
    }),
  ],
  leftover_of: null,
};

const PARTIAL: MealNutrition = {
  ...FIGURE,
  complete: false,
  coverage: 0.9,
  ingredients: [
    ing({}),
    ing({ name: "honey", grams: 1, status: "not_counted", reason: "amount_not_given", contribution: null }),
    ing({ name: "oil", grams: 240, status: "not_counted", reason: "frying_fat", contribution: null }),
  ],
};

const panelOf = (chip: HTMLElement): HTMLElement => {
  const panel = document.getElementById(chip.getAttribute("aria-controls") ?? "");
  if (!panel) throw new Error("the chip controls no panel");
  return panel;
};

describe("MealCard nutrition", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it("shows no chip without figures (setting off, loading, or none)", () => {
    renderCard();
    expect(screen.queryByRole("button", { name: /kcal|nutrition/i })).not.toBeInTheDocument();
  });

  it.each([
    ["a meal from before the weight rule", "legacy" as const],
    ["a leftover whose source is gone", "leftover_unresolved" as const],
  ])("shows nothing for %s", (_label, reason) => {
    renderCard({ nutrition: { ...FIGURE, per_serving: null, withheld_reason: reason }, nutritionSource: SOURCE });
    expect(screen.queryByRole("button", { name: /kcal|nutrition/i })).not.toBeInTheDocument();
  });

  it("rounds a complete figure to 10 kcal and opens the panel from the chip", async () => {
    const user = userEvent.setup();
    renderCard({ nutrition: FIGURE, nutritionSource: SOURCE });

    const chip = screen.getByRole("button", { name: "≈ 1,850 kcal per serving" });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Per serving, approximately")).not.toBeInTheDocument();

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-expanded", "true");
    const text = panelOf(chip).textContent ?? "";
    expect(text).toContain("Per serving, approximately");
    expect(text).toContain("1,850 kcal");
    expect(text).toContain("(7,750 kJ)");
    expect(text).toContain("42 g");
    expect(text).toContain("<1 g"); // fat 0.3 g
    expect(text).toContain("121 g");
    expect(text).toContain("The dish is split into 4 equal servings.");
    expect(text).toContain("not what any one person eats");
    // Provenance: Ciqual name and code, whole kcal so the sum can be redone.
    expect(text).toContain("Chicken, breast, raw (36018)");
    expect(text).toContain("484");
    // Water never reaches the table.
    expect(text).not.toMatch(/\bwater\b/);
    expect(text).toMatch(/insulin/);

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Per serving, approximately")).not.toBeInTheDocument();
  });

  it("carries the attribution, with the DOI link and the update date", async () => {
    const user = userEvent.setup();
    renderCard({ nutrition: FIGURE, nutritionSource: SOURCE });
    await user.click(screen.getByRole("button", { name: /kcal per serving/ }));

    const link = screen.getByRole("link", { name: "Ciqual 2025 (Anses)" });
    expect(link).toHaveAttribute("href", "https://doi.org/10.57745/RDMHWY");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link.parentElement?.textContent).toBe("Source: Ciqual 2025 (Anses), updated Nov 19, 2025");
  });

  it("marks a partial figure 'at least' and names what was left out", async () => {
    const user = userEvent.setup();
    renderCard({ nutrition: PARTIAL, nutritionSource: SOURCE });

    await user.click(screen.getByRole("button", { name: "At least 1,850 kcal per serving" }));
    expect(screen.getByText("Per serving, at least")).toBeInTheDocument();
    expect(
      screen.getByText("Not counted: honey (amount not given), oil (frying fat, amount eaten unknown)"),
    ).toBeInTheDocument();
  });

  it("says 'not enough data' below the coverage floor, and still explains why", async () => {
    const user = userEvent.setup();
    renderCard({
      nutrition: { ...PARTIAL, per_serving: null, withheld_reason: "coverage", coverage: 0.4 },
      nutritionSource: SOURCE,
    });

    await user.click(screen.getByRole("button", { name: "Not enough data for nutrition" }));
    expect(screen.getByText(/Too few of this meal's ingredients/)).toBeInTheDocument();
    expect(screen.queryByText(/Per serving/)).not.toBeInTheDocument();
    expect(screen.getByText(/^Not counted: honey/)).toBeInTheDocument();
    // The panel names its source whatever it shows.
    expect(screen.getByRole("link", { name: "Ciqual 2025 (Anses)" })).toBeInTheDocument();
  });

  it("gives a leftover its source's figure and points back to the original", async () => {
    const user = userEvent.setup();
    const link = { day_index: 0, meal_index: 0 };
    renderCard({
      meal: { ...MEAL, leftover_of: link },
      leftoverSource: "Day 1 · Chicken curry",
      nutrition: { ...FIGURE, ingredients: [], leftover_of: link },
      nutritionSource: SOURCE,
    });

    await user.click(screen.getByRole("button", { name: "≈ 1,850 kcal per serving" }));
    expect(screen.getByText(/Leftovers of an earlier meal/)).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /Ingredient/ })).not.toBeInTheDocument();
  });

  it("shortens the chip to kcal on mobile", () => {
    renderCard({ nutrition: PARTIAL, nutritionSource: SOURCE, isMobile: true });
    expect(screen.getByRole("button", { name: "At least 1,850 kcal" })).toBeInTheDocument();
  });

  it("formats Czech numbers and leaves no English behind", async () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    const user = userEvent.setup();
    renderCard({ nutrition: PARTIAL, nutritionSource: SOURCE });

    // U+00A0 between thousands: Intl's Czech grouping separator.
    const chip = screen.getByRole("button", { name: "Nejméně 1 850 kcal na porci" });
    await user.click(chip);
    const text = panelOf(chip).textContent ?? "";
    expect(text).toContain("Jídlo je rozdělené na 4 stejné porce.");
    expect(text).toContain("aktualizace 19. 11. 2025");
    expect(text).toContain("honey (množství není uvedené)");
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });
});
