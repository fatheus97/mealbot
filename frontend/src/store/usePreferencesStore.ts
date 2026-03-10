import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { DietType } from '../types';

interface PreferencesState {
  // Form Values
  days: number;
  dietType: DietType | "";
  mealsPerDay: number;
  peopleCount: number;
  tastePreferences: string;
  avoidIngredients: string;
  stockOnly: boolean;

  // Actions
  setDays: (days: number) => void;
  setDietType: (diet: DietType | "") => void;
  setMealsPerDay: (meals: number) => void;
  setPeopleCount: (count: number) => void;
  setTastePreferences: (tastes: string) => void;
  setAvoidIngredients: (avoids: string) => void;
  setStockOnly: (stockOnly: boolean) => void;
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      days: 3,
      dietType: "",
      mealsPerDay: 3,
      peopleCount: 2,
      tastePreferences: "",
      avoidIngredients: "",
      stockOnly: false,

      setDays: (days) => set({ days }),
      setDietType: (dietType) => set({ dietType }),
      setMealsPerDay: (mealsPerDay) => set({ mealsPerDay }),
      setPeopleCount: (peopleCount) => set({ peopleCount }),
      setTastePreferences: (tastePreferences) => set({ tastePreferences }),
      setAvoidIngredients: (avoidIngredients) => set({ avoidIngredients }),
      setStockOnly: (stockOnly) => set({ stockOnly }),
    }),
    {
      name: 'mealbot-preferences', // The key used in localStorage
    }
  )
);