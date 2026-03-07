import { describe, it, expect, beforeEach } from 'vitest';
import { usePreferencesStore } from './usePreferencesStore';

beforeEach(() => {
  usePreferencesStore.setState({
    days: 3,
    dietType: '',
    mealsPerDay: 3,
    peopleCount: 2,
    tastePreferences: '',
    avoidIngredients: '',
  });
});

describe('usePreferencesStore', () => {
  it('has correct initial defaults', () => {
    const state = usePreferencesStore.getState();
    expect(state.days).toBe(3);
    expect(state.mealsPerDay).toBe(3);
    expect(state.peopleCount).toBe(2);
    expect(state.dietType).toBe('');
    expect(state.tastePreferences).toBe('');
    expect(state.avoidIngredients).toBe('');
  });

  it('setDays updates days', () => {
    usePreferencesStore.getState().setDays(5);
    expect(usePreferencesStore.getState().days).toBe(5);
  });

  it('setDietType updates dietType', () => {
    usePreferencesStore.getState().setDietType('vegan');
    expect(usePreferencesStore.getState().dietType).toBe('vegan');
  });

  it('setMealsPerDay updates mealsPerDay', () => {
    usePreferencesStore.getState().setMealsPerDay(4);
    expect(usePreferencesStore.getState().mealsPerDay).toBe(4);
  });

  it('setPeopleCount updates peopleCount', () => {
    usePreferencesStore.getState().setPeopleCount(6);
    expect(usePreferencesStore.getState().peopleCount).toBe(6);
  });

  it('setTastePreferences updates tastePreferences', () => {
    usePreferencesStore.getState().setTastePreferences('spicy, sweet');
    expect(usePreferencesStore.getState().tastePreferences).toBe('spicy, sweet');
  });

  it('setAvoidIngredients updates avoidIngredients', () => {
    usePreferencesStore.getState().setAvoidIngredients('peanuts');
    expect(usePreferencesStore.getState().avoidIngredients).toBe('peanuts');
  });

  it('persist middleware saves to localStorage', () => {
    usePreferencesStore.getState().setDays(7);

    const stored = JSON.parse(localStorage.getItem('mealbot-preferences') ?? '{}');
    expect(stored.state?.days).toBe(7);
  });

  it('restores state from localStorage', () => {
    localStorage.setItem(
      'mealbot-preferences',
      JSON.stringify({
        state: { days: 5, dietType: 'vegan', mealsPerDay: 2, peopleCount: 4, tastePreferences: 'sour', avoidIngredients: 'gluten' },
        version: 0,
      }),
    );

    // Trigger rehydration
    usePreferencesStore.persist.rehydrate();

    const state = usePreferencesStore.getState();
    expect(state.days).toBe(5);
    expect(state.dietType).toBe('vegan');
    expect(state.peopleCount).toBe(4);
  });
});
