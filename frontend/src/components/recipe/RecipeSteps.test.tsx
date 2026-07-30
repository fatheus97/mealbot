import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { RecipeSteps } from './RecipeSteps';
import { FloatingTimers } from './FloatingTimers';
import { CookTimerProvider } from '../../contexts/CookTimerContext';

const STEPS = ['Opékejte 5 minut, dokud se nezatáhnou.', 'Add 200 g flour and serve.'];

afterEach(() => vi.useRealTimers());

describe('RecipeSteps', () => {
  it('renders plain text with no timerLabel', () => {
    render(
      <CookTimerProvider>
        <RecipeSteps steps={STEPS} />
      </CookTimerProvider>,
    );
    expect(screen.getByText(STEPS[0])).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  // The list also renders in places with no provider above it (isolated cards,
  // other tests). It must degrade rather than throw.
  it('renders plain text with no provider, even when a label is given', () => {
    render(<RecipeSteps steps={STEPS} timerLabel="Kuřecí nudličky" />);
    expect(screen.getByText(STEPS[0])).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('makes durations tappable and starts a timer, in the user\'s language', () => {
    vi.useFakeTimers();
    render(
      <CookTimerProvider>
        <RecipeSteps steps={STEPS} timerLabel="Kuřecí nudličky" reopenKey="cookmode:1:0:0" />
        <FloatingTimers />
      </CookTimerProvider>,
    );

    // Only the duration is a button — "200 g" is a quantity, not a time.
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveTextContent('5 minut');

    fireEvent.click(buttons[0]);

    // It shows up in the floating bubble, named after the meal.
    expect(screen.getByRole('group', { name: /timer for Kuřecí nudličky/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Timer 5:00 remaining/i)).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(30 * 1000);
    });
    expect(screen.getByLabelText(/Timer 4:30 remaining/i)).toBeInTheDocument();
  });

  it('keeps the step text intact around the button', () => {
    render(
      <CookTimerProvider>
        <RecipeSteps steps={[STEPS[0]]} timerLabel="Kuřecí nudličky" />
      </CookTimerProvider>,
    );
    expect(screen.getByRole('listitem')).toHaveTextContent(STEPS[0]);
  });

  it('inherits its colour so it is legible on any surface', () => {
    render(
      <CookTimerProvider>
        <RecipeSteps steps={STEPS} timerLabel="Kuřecí nudličky" />
      </CookTimerProvider>,
    );
    // The recurring dark-mode bug in this codebase is a hardcoded colour on an
    // unknown background. This list renders on the planner's light card, the
    // cookbook's parchment AND the adaptive page, so the affordance must not
    // pin a colour of its own.
    const style = screen.getByRole('button').style;
    expect(style.color).toBe('inherit');
    expect(style.borderBottom).toContain('dashed');
  });

  it('starts several timers from one recipe', () => {
    vi.useFakeTimers();
    render(
      <CookTimerProvider>
        <RecipeSteps
          steps={['Boil 10 minutes', 'Then rest 3 minutes']}
          timerLabel="Soup"
        />
        <FloatingTimers />
      </CookTimerProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/ }));
    fireEvent.click(screen.getByRole('button', { name: /^3 minutes$/ }));
    expect(screen.getAllByLabelText(/Timer .* remaining/i)).toHaveLength(2);
  });
});
