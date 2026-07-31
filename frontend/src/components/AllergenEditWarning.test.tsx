import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AllergenEditWarning } from './AllergenEditWarning';
import type { AllergenWarning } from '../types';

const milk: AllergenWarning = {
  allergen: 'milk',
  label: 'Milk',
  ingredient: 'double cream',
  source: 'ingredient',
};

const gluten: AllergenWarning = {
  allergen: 'cereals_with_gluten',
  label: 'Cereals containing gluten',
  ingredient: 'Serve with bread on the side.',
  source: 'step',
};

describe('AllergenEditWarning', () => {
  it('renders nothing when there are no warnings', () => {
    const { container } = render(
      <AllergenEditWarning warnings={[]} onDismiss={vi.fn()} />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('names the allergen and the offending ingredient', () => {
    render(<AllergenEditWarning warnings={[milk]} onDismiss={vi.fn()} />);
    expect(screen.getByText(/your edit added Milk/i)).toBeInTheDocument();
    expect(screen.getByText('double cream')).toBeInTheDocument();
  });

  it('says the change was saved anyway', () => {
    // The whole point of warn-don't-block: the user must not be left thinking
    // their edit was rejected.
    render(<AllergenEditWarning warnings={[milk]} onDismiss={vi.fn()} />);
    expect(screen.getByText(/we saved your change/i)).toBeInTheDocument();
  });

  it('marks a step hit as coming from a step', () => {
    // "bread" in the method reads very differently from "bread" in the
    // ingredient list — the user needs to know where to look.
    render(<AllergenEditWarning warnings={[gluten]} onDismiss={vi.fn()} />);
    expect(screen.getByText(/In a step:/)).toBeInTheDocument();
  });

  it('de-duplicates the headline when one allergen trips twice', () => {
    const second: AllergenWarning = { ...milk, ingredient: 'butter' };
    render(
      <AllergenEditWarning warnings={[milk, second]} onDismiss={vi.fn()} />,
    );
    // "Milk, Milk" would look broken.
    expect(screen.getByText(/your edit added Milk\./i)).toBeInTheDocument();
    // ...but both offending ingredients are still listed.
    expect(screen.getByText('double cream')).toBeInTheDocument();
    expect(screen.getByText('butter')).toBeInTheDocument();
  });

  it('lists at most four offenders so the dismiss button stays reachable', () => {
    const many = Array.from({ length: 9 }, (_, i) => ({
      ...milk,
      ingredient: `offender-${i}`,
    }));
    render(<AllergenEditWarning warnings={many} onDismiss={vi.fn()} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
  });

  it('is announced assertively', () => {
    // It appears after the save has already happened, so a polite region could
    // be missed entirely by a screen-reader user.
    render(<AllergenEditWarning warnings={[milk]} onDismiss={vi.fn()} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('calls onDismiss when the close button is clicked', async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(<AllergenEditWarning warnings={[milk]} onDismiss={onDismiss} />);

    await user.click(screen.getByRole('button', { name: /dismiss allergen warning/i }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('floats out of document flow so it cannot shift content', () => {
    // .claude/rules/frontend.md — a banner rendered IN flow above the editor
    // pushes the control the user is reaching for out from under the cursor.
    render(<AllergenEditWarning warnings={[milk]} onDismiss={vi.fn()} />);
    expect(screen.getByRole('alert')).toHaveStyle({ position: 'fixed' });
  });

  it('sets an explicit background AND colour so it survives dark mode', () => {
    // Inline styles cannot reach @media (prefers-color-scheme), so a surface
    // that sets only a background inherits the adaptive text colour and goes
    // white-on-white. Both must be present together.
    render(<AllergenEditWarning warnings={[milk]} onDismiss={vi.fn()} />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveStyle({ backgroundColor: '#fee2e2' });
    expect(alert).toHaveStyle({ color: '#7f1d1d' });
  });
});
