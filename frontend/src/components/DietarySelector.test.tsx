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

describe('sulphites disclosure', () => {
  it('still offers sulphites as a chip', () => {
    // Deliberately NOT removed. Declaring it still instructs the model to avoid
    // wine, vinegar and dried fruit — dropping the chip would take away the only
    // protection a sulphite-sensitive user gets, which is worse than the gap.
    render(
      <DietarySelector
        dietTypes={[]}
        allergens={[]}
        onToggleDiet={vi.fn()}
        onToggleAllergen={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Sulphites' })).toBeInTheDocument();
  });

  it('carries an info hint explaining it is not automatically checked', async () => {
    const user = userEvent.setup();
    render(
      <DietarySelector
        dietTypes={[]}
        allergens={[]}
        onToggleDiet={vi.fn()}
        onToggleAllergen={vi.fn()}
      />,
    );

    const hint = screen.getByRole('button', { name: /about sulphite screening/i });
    await user.click(hint);

    // The point of choice is where the difference has to be stated.
    expect(screen.getByText(/no automatic check/i)).toBeInTheDocument();
    expect(screen.getByText(/other 13 allergens/i)).toBeInTheDocument();
  });

  it('no other allergen carries a hint', () => {
    // If a second one ever needs one, that is a deliberate decision — not a
    // copy-paste. Exactly one is the invariant today.
    render(
      <DietarySelector
        dietTypes={[]}
        allergens={[]}
        onToggleDiet={vi.fn()}
        onToggleAllergen={vi.fn()}
      />,
    );
    expect(screen.getAllByRole('button', { name: /more information|about .* screening/i }))
      .toHaveLength(1);
  });

  it('keeps the no-guarantee wording and avoids the word "safe"', () => {
    // docs/dietary-reference.md Part 4 — the hint must not smuggle in a
    // reassurance the screen cannot back.
    render(
      <DietarySelector
        dietTypes={['vegan']}
        allergens={['sulphites']}
        onToggleDiet={vi.fn()}
        onToggleAllergen={vi.fn()}
      />,
    );
    expect(screen.getByText(/not a guarantee/i)).toBeInTheDocument();
    expect(screen.queryByText(/\bsafe\b/i)).not.toBeInTheDocument();
  });
});
