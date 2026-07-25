import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Allergen, DietType } from '../types';

export type PlannerMode = "plan_ahead" | "cook_now";

interface PreferencesState {
  // Form Values
  days: number;
  // Combinable dietary patterns + structured allergens (dietary differentiator
  // slice 5). Replaced the old single `dietType` — see the persist `migrate`.
  dietTypes: DietType[];
  allergens: Allergen[];
  mealsPerDay: number;
  peopleCount: number;
  tastePreferences: string;
  avoidIngredients: string;
  stockOnly: boolean;
  // Active tab in the planner; persisted so reloads land on the same mode.
  mode: PlannerMode;

  // Actions
  setDays: (days: number) => void;
  toggleDietType: (diet: DietType) => void;
  toggleAllergen: (allergen: Allergen) => void;
  setMealsPerDay: (meals: number) => void;
  setPeopleCount: (count: number) => void;
  setTastePreferences: (tastes: string) => void;
  setAvoidIngredients: (avoids: string) => void;
  setStockOnly: (stockOnly: boolean) => void;
  setMode: (mode: PlannerMode) => void;
  reset: () => void;
}

export const DEFAULT_PREFERENCES = {
  days: 3,
  // No diet selected by default — an empty list renders the prompt's
  // "balanced, varied nutrition" default (equivalent to the old "balanced").
  dietTypes: [] as DietType[],
  allergens: [] as Allergen[],
  mealsPerDay: 3,
  peopleCount: 2,
  tastePreferences: "Mediterranean, Italian, light",
  avoidIngredients: "",
  stockOnly: false,
  mode: "plan_ahead" as PlannerMode,
};

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      ...DEFAULT_PREFERENCES,

      setDays: (days) => set({ days }),
      toggleDietType: (diet) =>
        set((s) => ({ dietTypes: toggle(s.dietTypes, diet) })),
      toggleAllergen: (allergen) =>
        set((s) => ({ allergens: toggle(s.allergens, allergen) })),
      setMealsPerDay: (mealsPerDay) => set({ mealsPerDay }),
      setPeopleCount: (peopleCount) => set({ peopleCount }),
      setTastePreferences: (tastePreferences) => set({ tastePreferences }),
      setAvoidIngredients: (avoidIngredients) => set({ avoidIngredients }),
      setStockOnly: (stockOnly) => set({ stockOnly }),
      setMode: (mode) => set({ mode }),
      reset: () => set({ ...DEFAULT_PREFERENCES }),
    }),
    {
      name: 'mealbot-preferences', // The key used in localStorage
      version: 1,
      migrate: (persisted, version) => {
        // v0 stored a single `dietType: DietType | ""`. Widen it to the
        // combinable `dietTypes` list and add an empty `allergens` list, so a
        // returning user's saved diet isn't dropped on the upgrade.
        if (version === 0 && persisted && typeof persisted === 'object') {
          const old = persisted as Record<string, unknown>;
          const legacy = old.dietType;
          const dietTypes =
            typeof legacy === 'string' && legacy !== ''
              ? [legacy as DietType]
              : [];
          delete old.dietType;
          // Partial state; persist merges it over the store's actions/defaults.
          return { ...old, dietTypes, allergens: [] } as unknown as PreferencesState;
        }
        return persisted as PreferencesState;
      },
    }
  )
);
