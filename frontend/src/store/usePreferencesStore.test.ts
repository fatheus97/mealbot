import { describe, it, expect, beforeEach } from 'vitest';
import { usePreferencesStore, DEFAULT_PREFERENCES } from './usePreferencesStore';

beforeEach(() => {
  usePreferencesStore.setState({
    days: 3,
    dietTypes: [],
    allergens: [],
    mealsPerDay: 3,
    peopleCount: 2,
    tastePreferences: '',
    avoidIngredients: '',
  });
  localStorage.removeItem('mealbot-preferences');
});

describe('usePreferencesStore', () => {
  it('has correct initial defaults', () => {
    const state = usePreferencesStore.getState();
    expect(state.days).toBe(3);
    expect(state.mealsPerDay).toBe(3);
    expect(state.peopleCount).toBe(2);
    expect(state.dietTypes).toEqual([]);
    expect(state.allergens).toEqual([]);
    expect(state.tastePreferences).toBe('');
    expect(state.avoidIngredients).toBe('');
  });

  it('setDays updates days', () => {
    usePreferencesStore.getState().setDays(5);
    expect(usePreferencesStore.getState().days).toBe(5);
  });

  it('toggleDietType adds then removes a diet (combinable)', () => {
    const { toggleDietType } = usePreferencesStore.getState();
    toggleDietType('vegan');
    toggleDietType('gluten_free');
    expect(usePreferencesStore.getState().dietTypes).toEqual(['vegan', 'gluten_free']);
    toggleDietType('vegan');
    expect(usePreferencesStore.getState().dietTypes).toEqual(['gluten_free']);
  });

  it('toggleAllergen adds then removes an allergen', () => {
    const { toggleAllergen } = usePreferencesStore.getState();
    toggleAllergen('milk');
    toggleAllergen('peanuts');
    expect(usePreferencesStore.getState().allergens).toEqual(['milk', 'peanuts']);
    toggleAllergen('milk');
    expect(usePreferencesStore.getState().allergens).toEqual(['peanuts']);
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

  it('reset() restores defaults and clearStorage() wipes the persisted entry', async () => {
    const store = usePreferencesStore.getState();
    store.setDays(7);
    store.toggleDietType('vegan');
    store.toggleAllergen('milk');
    store.setTastePreferences('umami');
    store.setAvoidIngredients('gluten');

    expect(localStorage.getItem('mealbot-preferences')).not.toBeNull();

    usePreferencesStore.getState().reset();
    await usePreferencesStore.persist.clearStorage();

    const state = usePreferencesStore.getState();
    expect(state.days).toBe(DEFAULT_PREFERENCES.days);
    expect(state.dietTypes).toEqual(DEFAULT_PREFERENCES.dietTypes);
    expect(state.allergens).toEqual(DEFAULT_PREFERENCES.allergens);
    expect(state.mealsPerDay).toBe(DEFAULT_PREFERENCES.mealsPerDay);
    expect(state.peopleCount).toBe(DEFAULT_PREFERENCES.peopleCount);
    expect(state.tastePreferences).toBe(DEFAULT_PREFERENCES.tastePreferences);
    expect(state.avoidIngredients).toBe(DEFAULT_PREFERENCES.avoidIngredients);
    expect(state.stockOnly).toBe(DEFAULT_PREFERENCES.stockOnly);
    expect(localStorage.getItem('mealbot-preferences')).toBeNull();
  });

  it('migrates a v0 persisted single dietType to the combinable dietTypes list', () => {
    // A returning user upgraded from the single-select era: their saved
    // `dietType: 'vegan'` must widen to `dietTypes: ['vegan']`, not be dropped.
    localStorage.setItem(
      'mealbot-preferences',
      JSON.stringify({
        state: { days: 5, dietType: 'vegan', mealsPerDay: 2, peopleCount: 4, tastePreferences: 'sour', avoidIngredients: 'gluten' },
        version: 0,
      }),
    );

    usePreferencesStore.persist.rehydrate();

    const state = usePreferencesStore.getState();
    expect(state.days).toBe(5);
    expect(state.dietTypes).toEqual(['vegan']);
    expect(state.allergens).toEqual([]);
    expect(state.peopleCount).toBe(4);
    // The legacy scalar field is gone.
    expect((state as unknown as Record<string, unknown>).dietType).toBeUndefined();
  });
});
