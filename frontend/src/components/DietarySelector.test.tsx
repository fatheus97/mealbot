import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DietarySelector } from './DietarySelector';

describe('DietarySelector', () => {
  it('renders diet + allergen chips and the not-a-guarantee disclaimer', () => {
    render(
      <DietarySelector
        dietTypes={[]}
        allergens={[]}
        onToggleDiet={vi.fn()}
        onToggleAllergen={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Vegan' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Low-FODMAP' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tree nuts' })).toBeInTheDocument();
    // Transparency, not a guarantee (backend liability rule mirrored in the UI).
    expect(screen.getByText(/not a guarantee/i)).toBeInTheDocument();
    expect(screen.queryByText(/\bsafe\b/i)).not.toBeInTheDocument();
  });

  it('marks selected chips via aria-pressed', () => {
    render(
      <DietarySelector
        dietTypes={['vegan']}
        allergens={['milk']}
        onToggleDiet={vi.fn()}
        onToggleAllergen={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Vegan' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Keto' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Milk / dairy' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Peanuts' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('routes clicks to the correct toggle handler with the enum value', async () => {
    const onToggleDiet = vi.fn();
    const onToggleAllergen = vi.fn();
    const user = userEvent.setup();
    render(
      <DietarySelector
        dietTypes={[]}
        allergens={[]}
        onToggleDiet={onToggleDiet}
        onToggleAllergen={onToggleAllergen}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Gluten-free' }));
    expect(onToggleDiet).toHaveBeenCalledWith('gluten_free');
    await user.click(screen.getByRole('button', { name: 'Tree nuts' }));
    expect(onToggleAllergen).toHaveBeenCalledWith('tree_nuts');
    expect(onToggleAllergen).not.toHaveBeenCalledWith('gluten_free');
  });

  it('disables chips when disabled', () => {
    render(
      <DietarySelector
        dietTypes={[]}
        allergens={[]}
        onToggleDiet={vi.fn()}
        onToggleAllergen={vi.fn()}
        disabled
      />,
    );
    expect(screen.getByRole('button', { name: 'Vegan' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Milk / dairy' })).toBeDisabled();
  });
});
