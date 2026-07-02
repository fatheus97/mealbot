import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MealEditor } from './MealEditor';
import type { PlannedMeal } from '../../types';

function sampleMeal(): PlannedMeal {
  return {
    name: 'Tomato Soup',
    meal_type: 'soup',
    meal_type_label: 'Soup',
    ingredients: [
      { name: 'tomato', quantity_grams: 300, is_spice: false },
      { name: 'salt', quantity_grams: 5, is_spice: true },
    ],
    steps: ['Chop', 'Simmer'],
    total_time_minutes: 30,
  };
}

function renderEditor(overrides: Partial<PlannedMeal> = {}) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  render(
    <MealEditor
      meal={{ ...sampleMeal(), ...overrides }}
      onSave={onSave}
      onCancel={onCancel}
    />,
  );
  return { onSave, onCancel };
}

describe('MealEditor', () => {
  it('prefills the fields from the meal', () => {
    renderEditor();
    expect((screen.getByLabelText('Meal name') as HTMLInputElement).value).toBe('Tomato Soup');
    expect((screen.getByLabelText('Ingredient 1 name') as HTMLInputElement).value).toBe('tomato');
    expect((screen.getByLabelText('Ingredient 2 name') as HTMLInputElement).value).toBe('salt');
    expect((screen.getByLabelText('Step 1') as HTMLTextAreaElement).value).toBe('Chop');
  });

  it('saves edited content and preserves meal_type/meal_type_label', async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor();

    const nameInput = screen.getByLabelText('Meal name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Roasted Tomato Soup');
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const saved = onSave.mock.calls[0][0] as PlannedMeal;
    expect(saved.name).toBe('Roasted Tomato Soup');
    // Not editable — carried through untouched.
    expect(saved.meal_type).toBe('soup');
    expect(saved.meal_type_label).toBe('Soup');
    expect(saved.total_time_minutes).toBe(30);
    expect(saved.ingredients).toHaveLength(2);
  });

  it('adds a filled ingredient into the saved payload', async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor();

    await user.click(screen.getByRole('button', { name: /add ingredient/i }));
    await user.type(screen.getByLabelText('Ingredient 3 name'), 'basil');
    await user.clear(screen.getByLabelText('Ingredient 3 grams'));
    await user.type(screen.getByLabelText('Ingredient 3 grams'), '10');
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    const saved = onSave.mock.calls[0][0] as PlannedMeal;
    expect(saved.ingredients.map((i) => i.name)).toEqual(['tomato', 'salt', 'basil']);
  });

  it('drops empty ingredient rows on save', async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor();

    // Add a row but leave it blank — it must not reach the payload.
    await user.click(screen.getByRole('button', { name: /add ingredient/i }));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    const saved = onSave.mock.calls[0][0] as PlannedMeal;
    expect(saved.ingredients).toHaveLength(2);
  });

  it('removes an ingredient', async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor();

    await user.click(screen.getByRole('button', { name: /remove ingredient 1/i }));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    const saved = onSave.mock.calls[0][0] as PlannedMeal;
    expect(saved.ingredients.map((i) => i.name)).toEqual(['salt']);
  });

  it('removes a step', async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor();

    await user.click(screen.getByRole('button', { name: /remove step 1/i }));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    const saved = onSave.mock.calls[0][0] as PlannedMeal;
    expect(saved.steps).toEqual(['Simmer']);
  });

  it('disables Save when the name is blank', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.clear(screen.getByLabelText('Meal name'));
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
  });

  it('blocks Save with a message when an ingredient has no positive amount', async () => {
    const user = userEvent.setup();
    renderEditor();

    const grams = screen.getByLabelText('Ingredient 1 grams');
    await user.clear(grams);
    await user.type(grams, '0');

    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent(/positive amount/i);
  });

  it('clears total time to null when emptied', async () => {
    const user = userEvent.setup();
    const { onSave } = renderEditor();

    await user.clear(screen.getByLabelText('Total time in minutes'));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    const saved = onSave.mock.calls[0][0] as PlannedMeal;
    expect(saved.total_time_minutes).toBeNull();
  });

  it('calls onCancel without saving', async () => {
    const user = userEvent.setup();
    const { onSave, onCancel } = renderEditor();

    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});
