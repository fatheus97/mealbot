import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CookMode } from './CookMode';
import { parseDurationSeconds, tokenizeStepTimers, TIME_WORD_TABLES } from './cookMode.utils';
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

  // The bug this module was rewritten for: steps are written in the user's
  // `language` preference, so an English-only matcher left the timer feature
  // dead for every non-English user. `\b` cannot sit between "min" and "ut",
  // so Czech "5 minut" never matched at all.
  it.each([
    ['Czech', 'Vařte 5 minut, dokud se nezatáhnou', 300],
    ['Slovak', 'Varte 25 minút', 1500],
    ['Polish', 'Gotuj przez 15 minut', 900],
    ['German', '20 Minuten backen', 1200],
    ['Spanish', 'Cocinar durante 20 minutos', 1200],
    ['French', 'Cuire 45 minutes', 2700],
    ['Italian', 'Cuocere per 2 ore', 7200],
    ['Dutch', 'Bak 30 minuten', 1800],
    ['Swedish', 'Varken i 10 minuter', 600],
    ['Hungarian', 'Főzzük 10 percig', 600],
    ['Turkish', 'Pişirin 25 dakika', 1500],
    ['Russian', 'Готовьте 20 минут', 1200],
    ['Chinese', '加热5分钟', 300],
    ['Japanese', '5分間煮る', 300],
    ['Korean', '5분 동안 끓이세요', 300],
  ])('parses a duration written in %s', (_lang, step, expected) => {
    expect(parseDurationSeconds(step)).toBe(expected);
  });

  it('sums compound durations across scripts', () => {
    expect(parseDurationSeconds('Pečte 1 hodinu 30 minut')).toBe(5400);
    expect(parseDurationSeconds('1時間30分煮込む')).toBe(5400);
    expect(parseDurationSeconds('2 minuty 30 sekund')).toBe(150);
  });

  it('accepts seconds and the European decimal comma', () => {
    expect(parseDurationSeconds('Rest for 30 seconds')).toBe(30);
    expect(parseDurationSeconds('Odpočívat 45 sekund')).toBe(45);
    // "1,5 hodiny" is 90 minutes — a comma is a decimal point across most of
    // the EU, and the LLM writes in the user's locale.
    expect(parseDurationSeconds('Vařte 1,5 hodiny')).toBe(5400);
    expect(parseDurationSeconds('bake 1.5 hours')).toBe(5400);
  });

  it('does not arm a timer on quantities, temperatures or adjectives', () => {
    expect(parseDurationSeconds('Bake at 200 C until golden')).toBeNull();
    expect(parseDurationSeconds('Add 200 g flour and 2 eggs')).toBeNull();
    expect(parseDurationSeconds('Přidejte 2 lžíce oleje')).toBeNull();
    expect(parseDurationSeconds('Nakrájejte na 3 díly')).toBeNull();
    // The trailing-boundary guard: an adjective built on the unit stem is not a
    // duration mention. This is what the CJK branch must NOT regress.
    expect(parseDurationSeconds('A 5 minutová pauza')).toBeNull();
    // Over the 6h cap — a marinade, not a hands-on timer.
    expect(parseDurationSeconds('Marinate for 24 hours')).toBeNull();
    expect(parseDurationSeconds('Marinujte 24 hodin')).toBeNull();
  });

  it('keeps the word tables well-formed', () => {
    const { hour, minute, second } = TIME_WORD_TABLES;
    const all = [...hour, ...minute, ...second];
    // The alternation is interpolated into a RegExp unescaped, so a word
    // carrying a metacharacter would silently corrupt the whole pattern.
    // Combining marks count: Devanagari "घंटा" and Thai "ชั่วโมง" are \p{M}
    // sequences over their base letters, not bare \p{L}.
    for (const word of all) {
      expect(word, `"${word}" must be letters/marks only`).toMatch(/^[\p{L}\p{M}]+$/u);
    }
    // A word listed under two units would be counted twice by the summing
    // parser ("5 x" = 5h AND 5min), so the tables must stay disjoint.
    expect(new Set(all).size).toBe(all.length);
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

  // End-to-end regression for the reported bug: a plan generated with
  // `language = "Czech"` rendered its durations as inert text, so the feature
  // was invisible to any non-English user.
  it('arms a timer from a duration written in the user\'s language', () => {
    vi.useFakeTimers();
    try {
      renderCookMode({
        meal: {
          ...sampleMeal(),
          steps: ['Opékejte kuřecí nudličky 5 minut, dokud se nezatáhnou.'],
        },
      });
      fireEvent.click(screen.getByRole('button', { name: /^5 minut$/i }));
      expect(screen.getByLabelText(/Timer 5:00 remaining/i)).toBeInTheDocument();
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

  // Verbatim from a real generated plan — the step in the owner's bug report.
  it('tokenizes the reported Czech step without losing a character', () => {
    const step =
      'V hluboké pánvi rozehřejte 2 lžíce olivového oleje a opékejte na něm kuřecí nudličky 5 minut, dokud se nezatáhnou.';
    const segs = tokenizeStepTimers(step);
    const timed = segs.filter((s) => s.seconds != null);
    expect(timed).toHaveLength(1);
    expect(timed[0].text).toBe('5 minut');
    expect(timed[0].seconds).toBe(300);
    // "2 lžíce" (2 tablespoons) must stay inert text — only the duration is tappable.
    expect(segs.map((s) => s.text).join('')).toBe(step);
  });

  it('emits one token per duration when a step has several', () => {
    const segs = tokenizeStepTimers('Opékejte 5 minut, poté duste 20 minut');
    expect(segs.filter((s) => s.seconds != null).map((s) => s.seconds)).toEqual([300, 1200]);
  });

  it('binds a compound duration into a single token, not two competing ones', () => {
    const segs = tokenizeStepTimers('Pečte 1 hodinu 30 minut a vyndejte');
    const timed = segs.filter((s) => s.seconds != null);
    expect(timed).toHaveLength(1);
    expect(timed[0].text).toBe('1 hodinu 30 minut');
    expect(timed[0].seconds).toBe(5400);
  });
});
