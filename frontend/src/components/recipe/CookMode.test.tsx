import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CookMode } from './CookMode';
import { parseDurationSeconds, tokenizeStepTimers } from './cookMode.utils';
import { setMobileViewport } from '../../test/test-utils';
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
    steps: ['Chop the onion', 'Simmer for 10 minutes', 'Serve hot'],
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

describe('parseDurationSeconds', () => {
  it('parses minutes and hours; rejects bare numbers', () => {
    expect(parseDurationSeconds('Simmer for 10 minutes')).toBe(600);
    expect(parseDurationSeconds('bake 25 min')).toBe(1500);
    expect(parseDurationSeconds('rest 1 hour')).toBe(3600);
    expect(parseDurationSeconds('chill 90 mins')).toBe(5400);
    // Compound durations sum hours + minutes (not truncated to the first token).
    expect(parseDurationSeconds('Simmer for 1 hour 30 minutes')).toBe(5400);
    expect(parseDurationSeconds('2 hrs 15 min')).toBe(8100);
    expect(parseDurationSeconds('bake at 200 degrees')).toBeNull();
    expect(parseDurationSeconds('Serve hot')).toBeNull();
  });
});

describe('CookMode', () => {
  it('shows the first step and step progress', () => {
    renderCookMode();
    expect(screen.getByText('Chop the onion')).toBeInTheDocument();
    expect(screen.getByLabelText('Step 1 of 3')).toBeInTheDocument();
  });

  it('shows the ingredients panel as a full-screen overlay on mobile', async () => {
    setMobileViewport(true);
    const user = userEvent.setup();
    renderCookMode();
    // No panel until toggled.
    expect(document.querySelector('aside')).toBeNull();
    await user.click(screen.getByRole('button', { name: /^ingredients$/i }));

    const aside = document.querySelector('aside');
    expect(aside).not.toBeNull();
    // Mobile branch: full-screen overlay (absolute inset:0), not the desktop
    // side panel (which is position:static with a fixed width).
    expect(aside!.style.position).toBe('absolute');
    expect(aside!.textContent).toMatch(/tomato/i);
    // Still dismissable via the toggle.
    await user.click(screen.getByRole('button', { name: /^ingredients$/i }));
    expect(document.querySelector('aside')).toBeNull();
  });

  it('shows the ingredients panel as a side panel (not absolute) on desktop', async () => {
    setMobileViewport(false);
    const user = userEvent.setup();
    renderCookMode();
    await user.click(screen.getByRole('button', { name: /^ingredients$/i }));
    const aside = document.querySelector('aside');
    expect(aside).not.toBeNull();
    expect(aside!.style.position).not.toBe('absolute');
  });

  it('advances with Next and persists the step to localStorage', async () => {
    const user = userEvent.setup();
    renderCookMode();
    await user.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.getByLabelText('Step 2 of 3')).toBeInTheDocument();
    // Step 2's "10 minutes" renders as an inline tappable timer button.
    expect(screen.getByRole('button', { name: /^10 minutes$/i })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(KEY) as string).step).toBe(1);
  });

  it('goes back with Back', async () => {
    const user = userEvent.setup();
    renderCookMode();
    await user.click(screen.getByRole('button', { name: /next/i }));
    await user.click(screen.getByRole('button', { name: /back/i }));
    expect(screen.getByText('Chop the onion')).toBeInTheDocument();
  });

  it('swipes left for next step and right for previous', () => {
    renderCookMode();
    // The step-content div (parent of the step <p>) carries the touch handlers
    // and persists across step changes.
    const stepArea = screen.getByText('Chop the onion').parentElement!;

    // Swipe left (finger moves right → left) → next step.
    fireEvent.touchStart(stepArea, { changedTouches: [{ clientX: 300, clientY: 200 }] });
    fireEvent.touchEnd(stepArea, { changedTouches: [{ clientX: 200, clientY: 208 }] });
    expect(screen.getByLabelText('Step 2 of 3')).toBeInTheDocument();

    // Swipe right → previous step.
    fireEvent.touchStart(stepArea, { changedTouches: [{ clientX: 200, clientY: 200 }] });
    fireEvent.touchEnd(stepArea, { changedTouches: [{ clientX: 320, clientY: 196 }] });
    expect(screen.getByLabelText('Step 1 of 3')).toBeInTheDocument();
  });

  it('ignores taps and vertical scrolls (only decisive horizontal swipes page)', () => {
    renderCookMode();
    const stepArea = screen.getByText('Chop the onion').parentElement!;

    // Tap (no movement) — must not navigate.
    fireEvent.touchStart(stepArea, { changedTouches: [{ clientX: 200, clientY: 200 }] });
    fireEvent.touchEnd(stepArea, { changedTouches: [{ clientX: 205, clientY: 202 }] });
    expect(screen.getByLabelText('Step 1 of 3')).toBeInTheDocument();

    // Vertical-dominant drag (scrolling a long step) — must not navigate.
    fireEvent.touchStart(stepArea, { changedTouches: [{ clientX: 200, clientY: 100 }] });
    fireEvent.touchEnd(stepArea, { changedTouches: [{ clientX: 230, clientY: 300 }] });
    expect(screen.getByLabelText('Step 1 of 3')).toBeInTheDocument();
  });

  it('resumes from the saved step on mount', () => {
    localStorage.setItem(KEY, JSON.stringify({ step: 2 }));
    renderCookMode();
    expect(screen.getByText('Serve hot')).toBeInTheDocument();
    expect(screen.getByLabelText('Step 3 of 3')).toBeInTheDocument();
  });

  it('Done on the last step calls onDone and leaves storage for the parent', async () => {
    const user = userEvent.setup();
    localStorage.setItem(KEY, JSON.stringify({ step: 2 }));
    const { onDone } = renderCookMode({ doneLabel: 'Mark as cooked' });
    await user.click(screen.getByRole('button', { name: /mark as cooked/i }));
    expect(onDone).toHaveBeenCalledTimes(1);
    // CookMode does NOT clear storage itself — the parent clears it only after
    // the cook mutation succeeds, so a failed cook can resume from the same step.
    expect(localStorage.getItem(KEY)).not.toBeNull();
  });

  it('disables the manual timer for an over-cap (>6h) value', async () => {
    const user = userEvent.setup();
    renderCookMode();
    await user.type(screen.getByLabelText(/custom timer minutes/i), '999999');
    expect(screen.getByRole('button', { name: /set timer/i })).toBeDisabled();
  });

  it('Close calls onClose and keeps the saved step', async () => {
    const user = userEvent.setup();
    const { onClose } = renderCookMode();
    await user.click(screen.getByRole('button', { name: /next/i })); // writes step 1
    await user.click(screen.getByRole('button', { name: /close cooking mode/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(KEY)).not.toBeNull();
  });

  it('toggles the ingredients panel with amounts', async () => {
    const user = userEvent.setup();
    renderCookMode();
    await user.click(screen.getByRole('button', { name: /^ingredients$/i }));
    expect(screen.getByText(/tomato — 300g/i)).toBeInTheDocument();
  });

  it('makes a duration in the step a tappable timer and counts it down', () => {
    vi.useFakeTimers();
    try {
      renderCookMode();
      // Step 2 is "Simmer for 10 minutes" — the "10 minutes" itself is tappable.
      fireEvent.click(screen.getByRole('button', { name: /next/i }));
      fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
      expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(3000);
      });
      expect(screen.getByLabelText(/Timer 9:57 remaining/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('replaces a finished timer (silencing its alarm) when a new one starts', () => {
    vi.useFakeTimers();
    try {
      renderCookMode();
      fireEvent.click(screen.getByRole('button', { name: /next/i }));
      fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
      act(() => {
        vi.advanceTimersByTime(600 * 1000); // run it to completion
      });
      expect(screen.getByText(/time's up/i)).toBeInTheDocument();
      // Tapping the duration again restarts — the finished state is replaced
      // (startTimer calls stopAlarm, so the previous alarm can't keep ringing).
      fireEvent.click(screen.getByRole('button', { name: /^10 minutes$/i }));
      expect(screen.queryByText(/time's up/i)).toBeNull();
      expect(screen.getByLabelText(/Timer 10:00 remaining/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('navigates steps with the arrow keys', () => {
    renderCookMode();
    expect(screen.getByLabelText('Step 1 of 3')).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: 'ArrowRight' });
    expect(screen.getByLabelText('Step 2 of 3')).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: 'ArrowLeft' });
    expect(screen.getByLabelText('Step 1 of 3')).toBeInTheDocument();
  });

  it('surfaces a cook-failure error inside the overlay', () => {
    renderCookMode({ doneError: 'Something went wrong' });
    expect(screen.getByRole('alert')).toHaveTextContent(/something went wrong/i);
  });
});

describe('tokenizeStepTimers', () => {
  it('splits a duration mention into a tappable segment and preserves text', () => {
    const segs = tokenizeStepTimers('Simmer for 10 minutes until reduced');
    const timed = segs.filter((s) => s.seconds != null);
    expect(timed).toHaveLength(1);
    expect(timed[0].text).toBe('10 minutes');
    expect(timed[0].seconds).toBe(600);
    expect(segs.map((s) => s.text).join('')).toBe('Simmer for 10 minutes until reduced');
  });

  it('returns a single plain segment when there is no duration', () => {
    expect(tokenizeStepTimers('Serve hot')).toEqual([{ text: 'Serve hot', seconds: null }]);
  });
});
