import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { CookTimerProvider, useReopenTarget } from '../../contexts/CookTimerContext';
import { FloatingTimers } from './FloatingTimers';
import { CookMode } from './CookMode';
import type { PlannedMeal } from '../../types';

function sampleMeal(): PlannedMeal {
  return {
    name: 'Tomato Soup',
    meal_type: 'soup',
    meal_type_label: 'Soup',
    ingredients: [{ name: 'tomato', quantity_grams: 300, is_spice: false }],
    steps: ['Simmer for 10 minutes', 'Then rest 3 minutes'],
    total_time_minutes: 20,
  };
}

// Mirrors the real composition: cook mode opens and closes over a page that
// always has the bubble mounted (App renders both under one provider).
const KEY = 'cookmode:test:0:0';

// Stands in for a surface that can reopen cook mode (MealCard, CookNowForm):
// it registers itself as the way back for as long as it is mounted and allowed.
function Reopener({ onReopen, enabled = true }: { onReopen: () => void; enabled?: boolean }) {
  useReopenTarget(KEY, onReopen, enabled);
  return null;
}

function Harness({
  withReopen = true,
  reopenerMounted = true,
}: { withReopen?: boolean; reopenerMounted?: boolean } = {}) {
  const [open, setOpen] = useState(true);
  return (
    <CookTimerProvider>
      {reopenerMounted && <Reopener onReopen={() => setOpen(true)} enabled={withReopen} />}
      {open && (
        <CookMode
          meal={sampleMeal()}
          storageKey={KEY}
          onDone={() => setOpen(false)}
          onClose={() => setOpen(false)}
        />
      )}
      <button type="button" onClick={() => setOpen(true)}>
        reopen
      </button>
      <FloatingTimers />
    </CookTimerProvider>
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe('FloatingTimers', () => {
  it('shows nothing until a timer is running', () => {
    render(<Harness />);
    expect(screen.queryByRole('group', { name: /timer for/i })).toBeNull();
  });

  // The gap this closes: the timer used to be state inside the cook-mode
  // modal, so closing the overlay to check the fridge destroyed it.
  it('keeps a running timer alive after cook mode closes, in a bubble', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    // Hidden while cook mode is open — that surface shows its own timer bar.
    expect(screen.queryByRole('group', { name: /timer for/i })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));

    const bubble = screen.getByRole('group', { name: /timer for Tomato Soup/i });
    expect(bubble).toBeInTheDocument();
    expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();

    // And it keeps counting while cook mode is gone.
    act(() => {
      vi.advanceTimersByTime(90 * 1000);
    });
    expect(screen.getByLabelText(/Timer 8:30 remaining/i)).toBeInTheDocument();
  });

  it('hides the bubble again when cook mode reopens', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));
    expect(screen.getByRole('group', { name: /timer for/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /reopen/i }));
    expect(screen.queryByRole('group', { name: /timer for/i })).toBeNull();
    // Still the same timer, now shown in cook mode's own bar.
    expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();
  });

  it('pauses, resumes and dismisses from the bubble', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));

    fireEvent.click(screen.getByRole('button', { name: /^pause$/i }));
    act(() => {
      vi.advanceTimersByTime(60 * 1000);
    });
    // Paused time is not charged to the timer.
    expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^resume$/i }));
    act(() => {
      vi.advanceTimersByTime(30 * 1000);
    });
    expect(screen.getByLabelText(/Timer 9:30 remaining/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /dismiss timer for Tomato Soup/i }));
    expect(screen.queryByRole('group', { name: /timer for/i })).toBeNull();
  });

  it('announces a finished timer in the bubble', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));
    act(() => {
      vi.advanceTimersByTime(600 * 1000);
    });
    expect(screen.getByText(/time's up/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Timer 0:00 remaining/i)).toBeInTheDocument();
    // A finished timer offers no Pause/Resume, only dismissal.
    expect(screen.queryByRole('button', { name: /^pause$/i })).toBeNull();
  });

  // Timers are app-level and outlive the overlay, but only one CookMode is ever
  // mounted (MealPlanner keys it off a single `cookingMeal`). So another meal's
  // timer can show up in this meal's bar — it must say whose it is.
  it("names another meal's timer inside cook mode's bar", () => {
    function TwoMeals() {
      const [which, setWhich] = useState<'a' | 'b'>('a');
      const [open, setOpen] = useState(true);
      const meal = { ...sampleMeal(), name: which === 'a' ? 'Tomato Soup' : 'Beef Stew' };
      return (
        <CookTimerProvider>
          {open && (
            <CookMode
              meal={meal}
              storageKey={`cookmode:${which}`}
              onDone={() => setOpen(false)}
              onClose={() => setOpen(false)}
            />
          )}
          <button type="button" onClick={() => { setWhich('b'); setOpen(true); }}>
            cook the stew
          </button>
        </CookTimerProvider>
      );
    }
    render(<TwoMeals />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));
    fireEvent.click(screen.getByRole('button', { name: /cook the stew/i }));

    // The soup's timer is visible in the stew's bar and is attributed to the soup.
    expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();
    expect(screen.getByText('Tomato Soup')).toBeInTheDocument();
  });

  // Pausing reads the live clock. If the deadline slipped past in the up-to-1s
  // gap before the next tick, the timer must FINISH, not freeze at 0:00 as a
  // zombie that is neither running nor finished and so never rings.
  it('finishes rather than zombifying when paused just past the deadline', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));

    // Move the clock past the deadline without letting the interval fire, then
    // hit Pause in that window.
    act(() => {
      vi.setSystemTime(Date.now() + 601 * 1000);
    });
    fireEvent.click(screen.getByRole('button', { name: /^pause$/i }));

    expect(screen.getByText(/time's up/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^resume$/i })).toBeNull();
  });

  // The bubble is a way BACK into cooking, not just a readout.
  it('reopens cook mode on the step you left, without cancelling the timer', () => {
    render(<Harness />);
    // Move to step 2 so the restored step is not the default.
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    fireEvent.click(screen.getByRole('button', { name: /^3 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));
    expect(screen.getByRole('group', { name: /timer for/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /back to cooking Tomato Soup/i }));

    // Cook mode is back, on the step we left, and the timer kept running.
    expect(screen.getByLabelText('Step 2 of 2')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: /timer for/i })).toBeNull();
    expect(screen.getByLabelText(/Timer 3:00 remaining/i)).toBeInTheDocument();
  });

  it('renders no back-button when nothing can show that meal', () => {
    render(<Harness withReopen={false} />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));

    // The bubble still works as a readout with pause/dismiss — it just isn't a
    // link, rather than being a button that does nothing.
    expect(screen.getByRole('group', { name: /timer for/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /back to cooking/i })).toBeNull();
  });

  // A captured callback would still render as a live button here and silently
  // no-op — the Cook Now tab unmounting is an everyday action, not an edge case.
  it('stops offering a way back once the originating surface unmounts', () => {
    function Unmountable() {
      const [mounted, setMounted] = useState(true);
      return (
        <>
          <Harness reopenerMounted={mounted} />
          <button type="button" onClick={() => setMounted(false)}>
            switch tab
          </button>
        </>
      );
    }
    render(<Unmountable />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));
    expect(screen.getByRole('button', { name: /back to cooking/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /switch tab/i }));

    expect(screen.queryByRole('button', { name: /back to cooking/i })).toBeNull();
    // The timer itself is untouched — only the route back went away.
    expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();
  });

  // The guard can flip while the timer runs (meal marked cooked, plan finished).
  it('stops offering a way back once the meal is no longer cookable', () => {
    function Guarded() {
      const [cookable, setCookable] = useState(true);
      return (
        <>
          <Harness withReopen={cookable} />
          <button type="button" onClick={() => setCookable(false)}>
            mark cooked
          </button>
        </>
      );
    }
    render(<Guarded />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));
    expect(screen.getByRole('button', { name: /back to cooking/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /mark cooked/i }));

    expect(screen.queryByRole('button', { name: /back to cooking/i })).toBeNull();
    expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();
  });

  it('survives a lock screen while cook mode is closed', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
    fireEvent.click(screen.getByRole('button', { name: /close cooking mode/i }));

    // Clock moves without the interval firing, then the screen comes back.
    act(() => {
      vi.setSystemTime(Date.now() + 4 * 60 * 1000);
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(screen.getByLabelText(/Timer 6:00 remaining/i)).toBeInTheDocument();
  });
});
