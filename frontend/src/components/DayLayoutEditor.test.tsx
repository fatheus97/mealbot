import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DayLayoutEditor } from './DayLayoutEditor';
import type { MealType } from '../constants/mealTypes';

function renderEditor(initial: MealType[], onChange = vi.fn(), overrides: { maxSlots?: number; disabled?: boolean } = {}) {
  return { onChange, ...render(<DayLayoutEditor value={initial} onChange={onChange} {...overrides} />) };
}

describe('DayLayoutEditor', () => {
  it('shows the empty-state hint when value is empty', () => {
    renderEditor([]);
    expect(screen.getByText(/no default set/i)).toBeInTheDocument();
  });

  it('renders one select per slot, prefilled with the slot values', () => {
    renderEditor(['sweet_breakfast', 'main_course']);
    const selects = screen.getAllByRole('combobox');
    expect(selects).toHaveLength(2);
    expect((selects[0] as HTMLSelectElement).value).toBe('sweet_breakfast');
    expect((selects[1] as HTMLSelectElement).value).toBe('main_course');
  });

  it('adds a slot defaulting to main_course when + Add slot is clicked', async () => {
    const user = userEvent.setup();
    const { onChange } = renderEditor([]);
    await user.click(screen.getByRole('button', { name: /add slot/i }));
    expect(onChange).toHaveBeenCalledWith(['main_course']);
  });

  it('removes a slot via the ✕ button', async () => {
    const user = userEvent.setup();
    const { onChange } = renderEditor(['snack', 'main_course', 'dessert']);
    await user.click(screen.getByRole('button', { name: /remove slot 2/i }));
    expect(onChange).toHaveBeenCalledWith(['snack', 'dessert']);
  });

  it('reorders with up/down arrows', async () => {
    const user = userEvent.setup();
    const { onChange } = renderEditor(['snack', 'main_course', 'dessert']);

    // Move slot 3 up → should swap with slot 2
    await user.click(screen.getByRole('button', { name: /move slot 3 up/i }));
    expect(onChange).toHaveBeenLastCalledWith(['snack', 'dessert', 'main_course']);
  });

  it('disables the up button on the first slot and down on the last', () => {
    renderEditor(['snack', 'main_course']);
    expect(screen.getByRole('button', { name: /move slot 1 up/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /move slot 2 down/i })).toBeDisabled();
  });

  it('blocks adding beyond maxSlots', async () => {
    const user = userEvent.setup();
    const slots: MealType[] = Array(3).fill('main_course');
    const { onChange } = renderEditor(slots, vi.fn(), { maxSlots: 3 });
    const addBtn = screen.getByRole('button', { name: /add slot/i });
    expect(addBtn).toBeDisabled();
    await user.click(addBtn);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('disables every control when disabled=true', () => {
    renderEditor(['snack'], vi.fn(), { disabled: true });
    expect(screen.getByRole('combobox')).toBeDisabled();
    expect(screen.getByRole('button', { name: /add slot/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /remove slot 1/i })).toBeDisabled();
  });

  it('replaces a slot value when the select changes', async () => {
    const user = userEvent.setup();
    const { onChange } = renderEditor(['snack']);
    await user.selectOptions(screen.getByRole('combobox'), 'soup');
    expect(onChange).toHaveBeenCalledWith(['soup']);
  });
});
