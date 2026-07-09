import { describe, it, expect } from 'vitest';
import { mealTypeLabel } from './mealTypes';

describe('mealTypeLabel', () => {
  it('prefers a non-blank server-provided label', () => {
    expect(mealTypeLabel('soup', 'Polévka')).toBe('Polévka');
  });

  it('falls through a blank/whitespace server label to the enum label', () => {
    expect(mealTypeLabel('soup', '   ')).toBe('Soup');
    expect(mealTypeLabel('soup', '')).toBe('Soup');
    expect(mealTypeLabel('soup', null)).toBe('Soup');
    expect(mealTypeLabel('soup', undefined)).toBe('Soup');
  });

  it('maps known enum values to their English label', () => {
    expect(mealTypeLabel('main_course')).toBe('Main course');
    expect(mealTypeLabel('sweet_breakfast')).toBe('Sweet breakfast');
  });

  it('maps legacy breakfast/lunch/dinner values', () => {
    expect(mealTypeLabel('breakfast')).toBe('Breakfast');
    expect(mealTypeLabel('lunch')).toBe('Lunch');
    expect(mealTypeLabel('dinner')).toBe('Dinner');
  });

  it('titlecases an unknown value as a last resort', () => {
    expect(mealTypeLabel('mystery_meal')).toBe('Mystery Meal');
  });
});
