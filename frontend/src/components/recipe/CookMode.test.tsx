import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CookMode } from './CookMode';
import type { PlannedMeal } from '../../types';

const KEY = 'cookmode:test:0:0';

function sampleMeal(): PlannedMeal {
  return {
    name: 'Tomato Soup',
    meal_type: 'soup',
    meal_type_label: 'Soup',
    ingredients: [
      { name: 'tomato', quantity_grams: 300, is_spice: false },
      { name: 'salt', quantity_grams: 5, is_spice: true },
    ],
    steps: ['Chop', 'Simmer', 'Serve'],
    total_time_minutes: 20,
  };
}

function renderCookMode(overrides: Record<string, unknown> = {}) {
  const onDone = vi.fn();
  const onClose = vi.fn();
  render(
    <CookMode meal={sampleMeal()} storageKey={KEY} onDone={onDone} onClose={onClose} {...overrides} />,
  );
  return { onDone, onClose };
}

beforeEach(() => {
  localStorage.clear();
});

describe('CookMode', () => {
  it('renders ingredient and step checkboxes with a progress count', () => {
    renderCookMode();
    expect(screen.getByLabelText('Ingredient: tomato')).toBeInTheDocument();
    expect(screen.getByLabelText('Ingredient: salt')).toBeInTheDocument();
    expect(screen.getByLabelText('Step 1')).toBeInTheDocument();
    expect(screen.getByLabelText('Step 3')).toBeInTheDocument();
    expect(screen.getByLabelText(/0 of 3 steps done/i)).toBeInTheDocument();
  });

  it('updates the progress count and persists ticks to localStorage', async () => {
    const user = userEvent.setup();
    renderCookMode();
    await user.click(screen.getByLabelText('Step 1'));
    await user.click(screen.getByLabelText('Step 2'));
    expect(screen.getByLabelText(/2 of 3 steps done/i)).toBeInTheDocument();
    const stored = JSON.parse(localStorage.getItem(KEY) as string);
    expect([...stored.steps].sort()).toEqual([0, 1]);
  });

  it('loads existing progress from localStorage on mount', () => {
    localStorage.setItem(KEY, JSON.stringify({ ingredients: [0], steps: [2] }));
    renderCookMode();
    expect((screen.getByLabelText('Ingredient: tomato') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText('Step 3') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText('Step 1') as HTMLInputElement).checked).toBe(false);
    expect(screen.getByLabelText(/1 of 3 steps done/i)).toBeInTheDocument();
  });

  it('Done clears saved progress and calls onDone', async () => {
    const user = userEvent.setup();
    localStorage.setItem(KEY, JSON.stringify({ ingredients: [], steps: [0] }));
    const { onDone } = renderCookMode({ doneLabel: 'Mark as cooked' });
    await user.click(screen.getByRole('button', { name: /mark as cooked/i }));
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('Close keeps saved progress and calls onClose (resume later)', async () => {
    const user = userEvent.setup();
    const { onClose } = renderCookMode();
    await user.click(screen.getByLabelText('Step 1')); // writes progress
    await user.click(screen.getByRole('button', { name: /^close$/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(KEY)).not.toBeNull();
  });

  it('disables the done button while donePending', () => {
    renderCookMode({ donePending: true });
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();
  });
});
