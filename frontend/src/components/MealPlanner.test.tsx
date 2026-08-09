import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MealPlanner } from './MealPlanner';
import { AuthProvider } from '../contexts/AuthContext';
import { usePreferencesStore, DEFAULT_PREFERENCES } from '../store/usePreferencesStore';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { dayDateLabel, todayISO, addDaysISO } from '../utils/planDates';
import { setColorScheme } from '../test/media';
import { PAGE_TEXT } from '../constants/theme';
import type { ReactNode } from 'react';

/** jsdom normalises `style.color` to `rgb(r, g, b)`, so compare in that form
 *  rather than asserting a hex that will never match. */
function hexToRgb(hex: string): string {
  const int = parseInt(hex.slice(1), 16);
  return `rgb(${(int >> 16) & 255}, ${(int >> 8) & 255}, ${int & 255})`;
}

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
  recordWaste: vi.fn(),
}));

import { authFetch, fetchUserProfile, recordWaste } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedFetchProfile = fetchUserProfile as ReturnType<typeof vi.fn>;
const mockedRecordWaste = recordWaste as ReturnType<typeof vi.fn>;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

function loginUser() {
  localStorage.setItem('mealbot_token', 'test-token');
  localStorage.setItem('mealbot_user_id', '1');
  localStorage.setItem('mealbot_user_email', 'test@test.com');
}

// AuthProvider mounts with authFetch("/config"). Route by URL so that call
// doesn't consume the mock queue meant for /plan endpoints.
const okEmpty = () =>
  ({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
  }) as unknown as Response;

beforeEach(() => {
  vi.stubGlobal(
    'location',
    Object.defineProperties(
      {},
      {
        ...Object.getOwnPropertyDescriptors(window.location),
        reload: { configurable: true, value: vi.fn() },
      },
    ),
  );
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url === '/config') return Promise.resolve(okEmpty());
    return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
  });
});

// Some tests stub the Web Share / Clipboard APIs on navigator via
// Object.defineProperty; remove them after each test so a stub can't leak into
// a later test that assumes the API is absent.
afterEach(() => {
  Reflect.deleteProperty(navigator, 'share');
  Reflect.deleteProperty(navigator, 'clipboard');
});

describe('MealPlanner mode-tab colours follow the OS colour scheme', () => {
  // The tabs sit on the adaptive page background (index.css: #ffffff light,
  // #242424 dark) with no surface of their own, and inline styles can't reach
  // `@media (prefers-color-scheme)`. Shipped at 2.05:1 (inactive) and 3.00:1
  // (active) in dark mode. jsdom can't measure a ratio, so assert the branch —
  // the ratios themselves are pinned in test/contrast.test.ts.
  const tabColors = () => ({
    active: screen.getByRole('tab', { name: 'Plan Ahead' }).style.color,
    inactive: screen.getByRole('tab', { name: 'Cook Now' }).style.color,
  });

  function renderPlanAhead() {
    loginUser();
    usePreferencesStore.setState({ mode: 'plan_ahead' });
    render(<MealPlanner />, { wrapper: createWrapper() });
  }

  it('uses the light-surface colours when the OS asks for light', () => {
    setColorScheme('light');
    renderPlanAhead();
    expect(tabColors()).toEqual({
      active: hexToRgb(PAGE_TEXT.tabActive.light),
      inactive: hexToRgb(PAGE_TEXT.tabInactive.light),
    });
  });

  it('uses the dark-surface colours when the OS asks for dark', () => {
    setColorScheme('dark');
    renderPlanAhead();
    expect(tabColors()).toEqual({
      active: hexToRgb(PAGE_TEXT.tabActive.dark),
      inactive: hexToRgb(PAGE_TEXT.tabInactive.dark),
    });
  });

  it('carries the theme through to the active tab underline', () => {
    setColorScheme('dark');
    renderPlanAhead();
    // The underline is the same accent; leaving it on the light blue would put
    // a 3:1 rule under a 6:1 label.
    expect(screen.getByRole('tab', { name: 'Plan Ahead' }).style.borderBottom).toContain(
      hexToRgb(PAGE_TEXT.tabActive.dark),
    );
  });
});

describe('MealPlanner taste-preference cap', () => {
  // Tastes is free text, not chips, so it cannot be hard-capped mid-sentence.
  // The server keeps only the first 20 and says nothing about the rest, so the
  // UI has to — otherwise the entries are lost with no error and no log.
  // usePreferencesStore is PERSISTED, so seed it rather than typing: typing 100+
  // characters into a store-backed controlled input leaks the value into every
  // later test in the file (it broke the border-box test below when this suite
  // first used user.type).
  function renderWithTastes(tastes: string) {
    loginUser();
    usePreferencesStore.setState({ mode: 'plan_ahead', tastePreferences: tastes });
    render(<MealPlanner />, { wrapper: createWrapper() });
  }

  afterEach(() => {
    // Restore the REAL default, not ''. The store is persisted, so leaving a
    // value it would never naturally hold is the same order-dependent landmine
    // this suite seeds around in the first place.
    usePreferencesStore.setState({
      tastePreferences: DEFAULT_PREFERENCES.tastePreferences,
    });
  });

  it('says nothing while the entry is within the limit', () => {
    renderWithTastes(Array.from({ length: 20 }, (_, i) => `t${i}`).join(', '));
    expect(screen.queryByText(/Only the first/)).not.toBeInTheDocument();
  });

  it('warns once the entry exceeds what the server will keep', () => {
    renderWithTastes(Array.from({ length: 21 }, (_, i) => `t${i}`).join(', '));
    expect(
      screen.getByText('Only the first 20 will be used. You entered 21.'),
    ).toBeInTheDocument();
  });

  it('reserves the hint row so showing it cannot shove the fields below down', () => {
    renderWithTastes('spicy');
    // The container is always in the DOM (empty), never `{over && <div/>}` —
    // mounting it on demand is the CLS trap in .claude/rules/frontend.md.
    const input = screen.getByLabelText('Taste Preferences (comma separated):');
    const hint = input.nextElementSibling as HTMLElement;
    expect(hint).toBeTruthy();
    expect(hint.textContent).toBe('');
    expect(hint.style.minHeight).toBe('1rem');
  });
});

describe('MealPlanner', () => {
  it('returns null when logged out', () => {
    const { container } = render(<MealPlanner />, { wrapper: createWrapper() });
    expect(container.innerHTML).toBe('');
  });

  it('renders form inputs when logged in', () => {
    loginUser();
    render(<MealPlanner />, { wrapper: createWrapper() });

    expect(screen.getByText('Meal Planner')).toBeInTheDocument();
    expect(screen.getByText('Days to plan:')).toBeInTheDocument();
    expect(screen.getByText('Diets (combine any)')).toBeInTheDocument();
    expect(screen.getByText('Allergies to avoid')).toBeInTheDocument();
    expect(screen.getByText('Meals per day:')).toBeInTheDocument();
    expect(screen.getByText('People count:')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate plan/i })).toBeInTheDocument();
  });

  it('keeps full-width fields inside their container on narrow screens (#10)', () => {
    // These fields are `width: "100%"` under the default content-box model, so
    // their own border/padding pushed them past the container's right edge on
    // mobile. border-box makes width:100% inclusive of border/padding instead.
    loginUser();
    render(<MealPlanner />, { wrapper: createWrapper() });

    const fields = [
      screen.getByLabelText('Days to plan:'),
      screen.getByLabelText('Meals per day:'),
      screen.getByLabelText('People count:'),
      screen.getByLabelText('Taste Preferences (comma separated):'),
    ];
    for (const field of fields) {
      expect(getComputedStyle(field).boxSizing).toBe('border-box');
    }
  });

  it('disables generate button while pending', async () => {
    loginUser();

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      return new Promise(() => {}); // never resolves → button stays pending
    });

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    const button = screen.getByRole('button', { name: /generate plan/i });
    await user.click(button);

    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/generating/i);
  });

  it('shows error on generation failure', async () => {
    loginUser();
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      return Promise.resolve({
        ok: false,
        status: 500,
        text: () => Promise.resolve('Server error'),
      } as unknown as Response);
    });

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    await waitFor(() => {
      expect(screen.getByText(/plan generation failed/i)).toBeInTheDocument();
    });
  });

  it('renders plan and freeze/unfreeze toggles meal', async () => {
    loginUser();

    const planResponse = {
      plan_id: 1,
      days: [
        {
          meals: [
            {
              name: 'Scrambled Eggs',
              meal_type: 'breakfast',

              ingredients: [{ name: 'Eggs', quantity_grams: 200 }],
              steps: ['Crack eggs', 'Cook'],
            },
          ],
        },
      ],
      shopping_list: [{ name: 'Eggs', quantity_grams: 200 }],
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(planResponse),
      } as unknown as Response);
    });

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    await waitFor(() => {
      expect(screen.getByText('Scrambled Eggs')).toBeInTheDocument();
    });

    // Click freeze button (accessible name is text content "Freeze")
    const freezeBtn = screen.getByRole('button', { name: 'Freeze' });
    await user.click(freezeBtn);

    expect(screen.getByText('Frozen')).toBeInTheDocument();
    expect(screen.getByText(/1 meal\(s\) frozen/)).toBeInTheDocument();

    // Click again to unfreeze (now text content is "Frozen")
    await user.click(screen.getByRole('button', { name: 'Frozen' }));
    expect(screen.queryByText(/meal\(s\) frozen/)).not.toBeInTheDocument();
  });

  it('clears frozen styling on confirm so cooked-green can paint', async () => {
    loginUser();

    const planResponse = {
      plan_id: 7,
      days: [
        {
          meals: [
            {
              name: 'Scrambled Eggs',
              meal_type: 'breakfast',

              ingredients: [],
              steps: [],
            },
          ],
        },
      ],
      shopping_list: [],
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url.endsWith('/confirm')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({}),
        } as unknown as Response);
      }
      if (url.includes('/meal-entries') || url.includes('/meals')) {
        // useMealEntries poll — irrelevant for this test, return empty list.
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(planResponse),
      } as unknown as Response);
    });

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /generate plan/i }));
    await waitFor(() => expect(screen.getByText('Scrambled Eggs')).toBeInTheDocument());

    // Freeze the meal so the frozen state is populated. The meal container
    // is the parent of the BREAKFAST label — grab it so we can inspect its
    // inline backgroundColor across confirm.
    const mealLabel = screen.getByText(/BREAKFAST:/i);
    const mealContainer = mealLabel.closest('div[style]')?.parentElement as HTMLElement;
    expect(mealContainer).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Freeze' }));
    // Sanity: blue applied while frozen pre-confirm.
    expect(mealContainer.style.backgroundColor).toBe('rgb(238, 244, 251)');

    await user.click(screen.getByRole('button', { name: /confirm plan/i }));

    // Regression guard: previously `frozenMeals` was left populated after
    // confirm, so `isFrozen ? blue : isCooked ? green : transparent` kept
    // the meal blue forever and the cooked-green style could never paint.
    await waitFor(() => {
      expect(mealContainer.style.backgroundColor).toBe('transparent');
    });
  });

  it('regenerate sends correct frozen_meals', async () => {
    loginUser();

    const planResponse = {
      plan_id: 42,
      days: [
        {
          meals: [
            { name: 'Meal A', meal_type: 'breakfast', ingredients: [], steps: [] },
            { name: 'Meal B', meal_type: 'lunch', ingredients: [], steps: [] },
          ],
        },
      ],
      shopping_list: [],
    };

    const regeneratedPlan = { ...planResponse, days: [{ meals: [planResponse.days[0].meals[0], { ...planResponse.days[0].meals[1], name: 'Meal C' }] }] };

    // /plan/generate fires first, then /plan/42/regenerate after freeze.
    // Route by endpoint so /config doesn't perturb ordering.
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url.endsWith('/regenerate')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(regeneratedPlan),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(planResponse),
      } as unknown as Response);
    });

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    await waitFor(() => {
      expect(screen.getByText('Meal A')).toBeInTheDocument();
    });

    // Freeze first meal (accessible name is text content "Freeze")
    const freezeButtons = screen.getAllByRole('button', { name: 'Freeze' });
    await user.click(freezeButtons[0]);

    await user.click(screen.getByRole('button', { name: /regenerate unfrozen/i }));

    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/42/regenerate', {
        method: 'POST',
        body: JSON.stringify({ frozen_meals: [{ day_index: 0, meal_index: 0 }] }),
      });
    });
  });

  it('sends the selected diet_types + allergens (and no legacy diet_type) in the generate body', async () => {
    // The FE->BE contract line: diet/allergen selections from the store must be
    // assembled into the POST /plan body so the backend allergen screen sees
    // them. buildRequest is the link the isolated store/component tests miss.
    loginUser();
    // mockedAuthFetch.mock.calls accumulates across tests in this file (the
    // beforeEach only re-sets the implementation, never the call history), so
    // reset it here — otherwise the find('/plan?') below would match an EARLIER
    // test's generate call and assert on its (empty-diet) payload.
    mockedAuthFetch.mockReset();
    // Seed the persisted store singleton with a known selection.
    usePreferencesStore.setState({ dietTypes: ['vegan'], allergens: ['peanuts'] });

    const planResponse = {
      plan_id: 7,
      start_date: null,
      days: [{ meals: [] }],
      shopping_list: [],
    };
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(planResponse),
      } as unknown as Response);
    });

    try {
      const user = userEvent.setup();
      render(<MealPlanner />, { wrapper: createWrapper() });
      await user.click(screen.getByRole('button', { name: /generate plan/i }));

      const isGenerateCall = (call: unknown[]) =>
        typeof call[0] === 'string' && call[0].startsWith('/plan?');
      await waitFor(() =>
        expect(mockedAuthFetch.mock.calls.some(isGenerateCall)).toBe(true),
      );

      const generateCall = mockedAuthFetch.mock.calls.find(isGenerateCall);
      const body = JSON.parse(generateCall?.[1]?.body ?? 'null') as {
        diet_types?: unknown;
        allergens?: unknown;
        diet_type?: unknown;
      };
      expect(body.diet_types).toEqual(['vegan']);
      expect(body.allergens).toEqual(['peanuts']);
      // The multi-select UI no longer sends the legacy scalar — backend reconciles.
      expect(body.diet_type).toBeUndefined();
    } finally {
      // Don't leak the selection into sibling tests that share the store singleton.
      usePreferencesStore.setState({ dietTypes: [], allergens: [] });
    }
  });

  it('round-trips "ingredients to avoid" chips through the persisted store into the body', async () => {
    // Ticket #2: MealPlanner's avoid field is the riskier half of the change — the
    // chip list (string[]) round-trips through a PERSISTED store STRING (join on
    // write, parseList on read). Verify both add and remove land in avoid_ingredients.
    loginUser();
    mockedAuthFetch.mockReset();
    usePreferencesStore.setState({ avoidIngredients: '' });

    const planResponse = { plan_id: 7, start_date: null, days: [{ meals: [] }], shopping_list: [] };
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(planResponse),
      } as unknown as Response);
    });

    try {
      const user = userEvent.setup();
      render(<MealPlanner />, { wrapper: createWrapper() });

      const avoid = screen.getByPlaceholderText(/to avoid and press enter/i);
      await user.type(avoid, 'peanuts{Enter}cilantro{Enter}');
      // Remove the first chip → exercises the remove → persisted-string update path.
      await user.click(screen.getByRole('button', { name: 'Remove peanuts' }));

      await user.click(screen.getByRole('button', { name: /generate plan/i }));

      const isGenerateCall = (call: unknown[]) =>
        typeof call[0] === 'string' && call[0].startsWith('/plan?');
      await waitFor(() =>
        expect(mockedAuthFetch.mock.calls.some(isGenerateCall)).toBe(true),
      );

      const generateCall = mockedAuthFetch.mock.calls.find(isGenerateCall);
      const body = JSON.parse(generateCall?.[1]?.body ?? 'null') as { avoid_ingredients?: unknown };
      expect(body.avoid_ingredients).toEqual(['cilantro']);
    } finally {
      usePreferencesStore.setState({ avoidIngredients: '' });
    }
  });

  it('scrolls to the plan on mount when initialPlan is provided', () => {
    loginUser();

    const scrollIntoView = vi.fn();
    // scrollIntoView isn't implemented in jsdom — stub it on the prototype so
    // any element's call lands on the spy.
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });

    const initialPlan = {
      plan_id: 99,
      start_date: null,
      days: [
        {
          meals: [
            {
              name: 'Opened Meal',
              meal_type: 'lunch',

              ingredients: [],
              steps: [],
            },
          ],
        },
      ],
      shopping_list: [],
    };

    render(<MealPlanner initialPlan={initialPlan} />, { wrapper: createWrapper() });

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
  });

  it('does not scroll on mount when no initialPlan is provided', () => {
    loginUser();

    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });

    render(<MealPlanner />, { wrapper: createWrapper() });

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it('renders real-world dates in the day headers of a scheduled plan', async () => {
    loginUser();
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url.includes('/meals'))
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
      return Promise.resolve(okEmpty());
    });

    // An opened (confirmed) plan reads its date from the server value on
    // currentPlan; Day 1 falls on start_date, Day 2 the next day.
    const initialPlan = {
      plan_id: 91,
      start_date: '2026-08-01',
      days: [
        { meals: [{ name: 'Day1 Meal', meal_type: 'lunch', ingredients: [], steps: [] }] },
        { meals: [{ name: 'Day2 Meal', meal_type: 'dinner', ingredients: [], steps: [] }] },
      ],
      shopping_list: [],
    };
    const initialSummary = {
      id: 91, start_date: '2026-08-01', created_at: new Date().toISOString(), days: 2,
      meals_per_day: 1, people_count: 2, status: 'planned' as const, total_meals: 2,
      cooked_meals: 0, finished_at: null,
    };

    render(
      <MealPlanner initialPlan={initialPlan} initialSummary={initialSummary} />,
      { wrapper: createWrapper() },
    );

    // Assert the exact labels the component's own formatter produces. The
    // locale comes from the store rather than being hardcoded, so this keeps
    // matching if the suite's default ever changes — the component reads the
    // same value.
    const locale = useLocaleStore.getState().locale;
    await waitFor(() =>
      expect(
        screen.getByText(dayDateLabel('2026-08-01', 0, locale)!, { exact: false }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(dayDateLabel('2026-08-01', 1, locale)!, { exact: false }),
    ).toBeInTheDocument();
  });

  it('renders total cook time badge only when present', async () => {
    loginUser();

    const planResponse = {
      plan_id: 1,
      days: [
        {
          meals: [
            {
              name: 'Timed Meal',
              meal_type: 'lunch',

              ingredients: [],
              steps: [],
              total_time_minutes: 35,
            },
            {
              name: 'Legacy Meal',
              meal_type: 'dinner',

              ingredients: [],
              steps: [],
              // total_time_minutes intentionally omitted — simulates a plan from
              // before this feature shipped.
            },
          ],
        },
      ],
      shopping_list: [],
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(planResponse),
      } as unknown as Response);
    });

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /generate plan/i }));

    await waitFor(() => {
      expect(screen.getByText('Timed Meal')).toBeInTheDocument();
    });

    // Present for the meal that has total_time_minutes.
    expect(screen.getByLabelText(/total time 35 minutes/i)).toBeInTheDocument();
    expect(screen.getByText(/· 35 min/)).toBeInTheDocument();

    // Absent for the legacy meal — only one badge should exist total.
    expect(screen.queryAllByLabelText(/total time .* minutes/i)).toHaveLength(1);
  });

  // Regression: the Cook Now / Plan Ahead mode tabs must stay visible while
  // viewing an opened plan (My Plans → Open). PR #89 had hidden them, which
  // stranded the user with no way to switch modes without reloading.
  it('keeps the Cook Now / Plan Ahead tabs visible when an opened plan is shown', () => {
    loginUser();

    const initialPlan = {
      plan_id: 77,
      start_date: null,
      days: [
        {
          meals: [
            { name: 'Opened Meal', meal_type: 'lunch', ingredients: [], steps: [] },
          ],
        },
      ],
      shopping_list: [],
    };

    render(<MealPlanner initialPlan={initialPlan} />, { wrapper: createWrapper() });

    expect(screen.getByRole('tab', { name: /cook now/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /plan ahead/i })).toBeInTheDocument();
    // Plan Ahead is forced-selected while viewing an opened plan.
    expect(screen.getByRole('tab', { name: /plan ahead/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('calls onExitPlan when switching tabs while an opened plan is shown', async () => {
    loginUser();

    const initialPlan = {
      plan_id: 77,
      start_date: null,
      days: [
        {
          meals: [
            { name: 'Opened Meal', meal_type: 'lunch', ingredients: [], steps: [] },
          ],
        },
      ],
      shopping_list: [],
    };
    const onExitPlan = vi.fn();

    const user = userEvent.setup();
    render(
      <MealPlanner initialPlan={initialPlan} onExitPlan={onExitPlan} />,
      { wrapper: createWrapper() },
    );

    await user.click(screen.getByRole('tab', { name: /cook now/i }));

    expect(onExitPlan).toHaveBeenCalledTimes(1);
  });

  // Clicking the currently-active Plan Ahead tab while viewing an opened
  // plan is the non-obvious case: it's the highlighted tab, but it still
  // exits the opened plan. See the comment near `effectiveMode`.
  it('calls onExitPlan when clicking the active Plan Ahead tab with an opened plan', async () => {
    loginUser();

    const initialPlan = {
      plan_id: 77,
      start_date: null,
      days: [
        {
          meals: [
            { name: 'Opened Meal', meal_type: 'lunch', ingredients: [], steps: [] },
          ],
        },
      ],
      shopping_list: [],
    };
    const onExitPlan = vi.fn();

    const user = userEvent.setup();
    render(
      <MealPlanner initialPlan={initialPlan} onExitPlan={onExitPlan} />,
      { wrapper: createWrapper() },
    );

    await user.click(screen.getByRole('tab', { name: /plan ahead/i }));

    expect(onExitPlan).toHaveBeenCalledTimes(1);
  });

  it('does not call onExitPlan when no plan is opened', async () => {
    loginUser();

    const onExitPlan = vi.fn();
    const user = userEvent.setup();
    render(<MealPlanner onExitPlan={onExitPlan} />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('tab', { name: /cook now/i }));

    expect(onExitPlan).not.toHaveBeenCalled();
  });

  it('shows Un-confirm after confirming and calls /unconfirm when clicked', async () => {
    loginUser();

    const planResponse = {
      plan_id: 55,
      days: [
        {
          meals: [
            { name: 'Egg Scramble', meal_type: 'breakfast', ingredients: [], steps: [] },
          ],
        },
      ],
      shopping_list: [],
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url.endsWith('/unconfirm')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      if (url.endsWith('/confirm')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      if (url.includes('/meals')) {
        // Empty meal entries → no cooked meals → Un-confirm should be visible.
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(planResponse),
      } as unknown as Response);
    });

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    // Earlier tests in this file end with mode=cook_now (persisted in
    // zustand) so the Plan Ahead form isn't rendered on mount. Click the
    // Plan Ahead tab to force the right mode regardless of test order.
    await user.click(screen.getByRole('tab', { name: /plan ahead/i }));

    await user.click(screen.getByRole('button', { name: /generate plan/i }));
    await waitFor(() => expect(screen.getByText('Egg Scramble')).toBeInTheDocument());

    // Pre-confirm: no Un-confirm button.
    expect(screen.queryByRole('button', { name: /un-confirm/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /confirm plan/i }));

    // Post-confirm: Un-confirm appears.
    const unconfirmBtn = await screen.findByRole('button', { name: /un-confirm$/i });
    await user.click(unconfirmBtn);

    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/55/unconfirm', { method: 'POST' });
    });

    // After successful un-confirm, header reverts and the button is gone.
    await waitFor(() => {
      expect(screen.getByText(/your generated plan/i)).toBeInTheDocument();
    });
  });

  it('hides Un-confirm when at least one meal is cooked', async () => {
    loginUser();

    const initialPlan = {
      plan_id: 60,
      start_date: null,
      days: [{ meals: [{ name: 'Egg Scramble', meal_type: 'breakfast', ingredients: [], steps: [] }] }],
      shopping_list: [],
    };
    const initialSummary = {
      id: 60,
      start_date: null,
      created_at: new Date().toISOString(),
      days: 1,
      meals_per_day: 1,
      people_count: 2,
      status: 'active' as const,
      total_meals: 1,
      cooked_meals: 1,
      finished_at: null,
    };
    const cookedEntry = {
      id: 1, day_index: 1, meal_index: 1, name: 'Egg Scramble',
      meal_type: 'breakfast', cooked_at: new Date().toISOString(), is_favorite: false,
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url.includes('/meals')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve([cookedEntry]),
        } as unknown as Response);
      }
      return Promise.resolve(okEmpty());
    });

    render(
      <MealPlanner initialPlan={initialPlan} initialSummary={initialSummary} />,
      { wrapper: createWrapper() },
    );

    // Wait for meal entries to load — once mealEntries reports a cooked entry,
    // the Un-confirm button must not appear.
    await waitFor(() => {
      expect(screen.getByText('Egg Scramble')).toBeInTheDocument();
    });

    // Give react-query a tick to process the meal entries fetch.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /un-confirm$/i })).not.toBeInTheDocument();
    });
  });

  it('shows Reopen on a finished plan and calls /reopen when clicked', async () => {
    loginUser();

    const initialPlan = {
      plan_id: 70,
      start_date: null,
      days: [{ meals: [{ name: 'Stew', meal_type: 'dinner', ingredients: [], steps: [] }] }],
      shopping_list: [],
    };
    const initialSummary = {
      id: 70,
      start_date: null,
      created_at: new Date().toISOString(),
      days: 1,
      meals_per_day: 1,
      people_count: 2,
      status: 'finished' as const,
      total_meals: 1,
      cooked_meals: 0,
      finished_at: new Date().toISOString(),
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url.endsWith('/reopen')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      if (url.includes('/meals')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      return Promise.resolve(okEmpty());
    });

    const user = userEvent.setup();
    render(
      <MealPlanner initialPlan={initialPlan} initialSummary={initialSummary} />,
      { wrapper: createWrapper() },
    );

    // Finished plan: Reopen visible, Un-confirm/Finish hidden.
    expect(screen.getByText(/finished plan/i)).toBeInTheDocument();
    const reopenBtn = await screen.findByRole('button', { name: /^reopen$/i });
    expect(screen.queryByRole('button', { name: /un-confirm/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /finish plan/i })).not.toBeInTheDocument();

    await user.click(reopenBtn);

    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/70/reopen', { method: 'POST' });
    });

    // After reopen, header reverts to "Confirmed Plan".
    await waitFor(() => {
      expect(screen.getByText(/confirmed plan/i)).toBeInTheDocument();
    });
  });

  it('surfaces server 409 detail message on reopen failure', async () => {
    loginUser();

    const initialPlan = {
      plan_id: 80,
      start_date: null,
      days: [{ meals: [{ name: 'Stew', meal_type: 'dinner', ingredients: [], steps: [] }] }],
      shopping_list: [],
    };
    const initialSummary = {
      id: 80, start_date: null, created_at: new Date().toISOString(), days: 1, meals_per_day: 1,
      people_count: 2, status: 'finished' as const, total_meals: 1, cooked_meals: 0,
      finished_at: new Date().toISOString(),
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url.endsWith('/reopen')) {
        return Promise.resolve({
          ok: false, status: 409,
          json: () => Promise.resolve({
            detail: 'Not enough chicken in fridge to reopen this plan: need 300g, have 0g.',
          }),
        } as unknown as Response);
      }
      if (url.includes('/meals')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      return Promise.resolve(okEmpty());
    });

    const user = userEvent.setup();
    render(
      <MealPlanner initialPlan={initialPlan} initialSummary={initialSummary} />,
      { wrapper: createWrapper() },
    );

    const reopenBtn = await screen.findByRole('button', { name: /^reopen$/i });
    await user.click(reopenBtn);

    // Server `detail` must be propagated, not swallowed into a bare status.
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/not enough chicken/i);
    });

    // Plan stays finished — failure must not flip local state.
    expect(screen.getByText(/finished plan/i)).toBeInTheDocument();
  });

  // --- Shopping list: copy / share / check-off (frontend-only, no backend) ---

  const shoppingPlan = {
    plan_id: 123,
    days: [
      { meals: [{ name: 'Omelette', meal_type: 'breakfast', ingredients: [], steps: [] }] },
    ],
    shopping_list: [
      { name: 'Eggs', quantity_grams: 200 },
      { name: 'Milk', quantity_grams: 500 },
    ],
  };

  // Log in, generate a plan whose response carries a 2-item shopping list, and
  // wait for the Shopping List card to render. Returns the userEvent instance.
  async function renderWithShoppingList() {
    loginUser();
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(shoppingPlan),
      } as unknown as Response);
    });
    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });
    // Force Plan Ahead — zustand's persisted mode is cleared between tests but
    // its default isn't guaranteed to be plan_ahead (mirrors the un-confirm test).
    await user.click(screen.getByRole('tab', { name: /plan ahead/i }));
    await user.click(screen.getByRole('button', { name: /generate plan/i }));
    await screen.findByText('Shopping List');
    return user;
  }

  it('Copy writes the shopping list to the clipboard and confirms', async () => {
    const user = await renderWithShoppingList();

    // userEvent.setup() installs its OWN navigator.clipboard stub, so our spy
    // must be defined AFTER render (inside renderWithShoppingList) to win.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    const copyBtn = screen.getByRole('button', { name: /copy shopping list/i });
    expect(copyBtn).toHaveTextContent(/^Copy$/);

    await user.click(copyBtn);

    expect(writeText).toHaveBeenCalledTimes(1);
    // Newline-joined "name — grams" lines, quantities rounded. Assert structure
    // (not the exact dash glyph) so the test isn't brittle to punctuation.
    const text = writeText.mock.calls[0][0] as string;
    const lines = text.split('\n');
    expect(lines).toHaveLength(2);
    expect(lines[0]).toContain('Eggs');
    expect(lines[0]).toContain('200g');
    expect(lines[1]).toContain('Milk');
    expect(lines[1]).toContain('500g');

    // Label flips to the copied affordance once the clipboard promise resolves.
    await waitFor(() => expect(copyBtn).toHaveTextContent(/Copied/));
  });

  it('does not render Share when the Web Share API is unavailable', async () => {
    Reflect.deleteProperty(navigator, 'share');

    await renderWithShoppingList();

    expect(screen.getByRole('button', { name: /copy shopping list/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /share shopping list/i })).not.toBeInTheDocument();
  });

  it('renders Share and invokes navigator.share when supported', async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', { configurable: true, value: share });

    const user = await renderWithShoppingList();
    await user.click(screen.getByRole('button', { name: /share shopping list/i }));

    expect(share).toHaveBeenCalledTimes(1);
    const arg = share.mock.calls[0][0] as { title: string; text: string };
    expect(arg.title).toBe('Shopping List');
    expect(arg.text).toContain('Eggs');
    expect(arg.text).toContain('Milk');
  });

  it('ticks a shopping-list item (strike-through) and unticks it', async () => {
    const user = await renderWithShoppingList();

    const checkbox = screen.getByRole('checkbox', { name: /mark eggs as bought/i });
    const span = checkbox.closest('label')?.querySelector('span');
    expect(checkbox).not.toBeChecked();
    expect(span).toHaveStyle({ textDecoration: 'none' });

    await user.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(span).toHaveStyle({ textDecoration: 'line-through' });

    await user.click(checkbox);
    expect(checkbox).not.toBeChecked();
    expect(span).toHaveStyle({ textDecoration: 'none' });
  });

  it('clears ticks when a new plan is generated (no stale indices)', async () => {
    const user = await renderWithShoppingList();

    await user.click(screen.getByRole('checkbox', { name: /mark eggs as bought/i }));
    expect(screen.getByRole('checkbox', { name: /mark eggs as bought/i })).toBeChecked();

    // Regenerating via a fresh generate replaces the list — ticks must reset so
    // a checked index never maps onto a different item.
    await user.click(screen.getByRole('button', { name: /generate plan/i }));
    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: /mark eggs as bought/i })).not.toBeChecked(),
    );
  });
});

describe('MealPlanner — expired-item review after finishing', () => {
  const PLAN_ID = 900;

  const initialPlan = {
    plan_id: PLAN_ID,
    start_date: null,
    days: [{ meals: [{ name: 'Stew', meal_type: 'dinner', ingredients: [], steps: [] }] }],
    shopping_list: [],
  };
  const initialSummary = {
    id: PLAN_ID, start_date: null, created_at: new Date().toISOString(), days: 1,
    meals_per_day: 1, people_count: 2, status: 'active' as const, total_meals: 1,
    cooked_meals: 0, finished_at: null,
  };

  /** An expired batch and a fresh one, so the filter has something to exclude. */
  const EXPIRED = {
    id: 11, name: 'Yogurt', quantity_grams: 500,
    need_to_use: true, expiration_date: addDaysISO(todayISO(), -4),
  };
  const FRESH = {
    id: 12, name: 'Rice', quantity_grams: 900,
    need_to_use: false, expiration_date: addDaysISO(todayISO(), 30),
  };

  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
    mockedRecordWaste.mockReset();
    mockedRecordWaste.mockResolvedValue({ recorded: 1 });
    mockedFetchProfile.mockReset();
    // `mock.calls` ACCUMULATES across tests — the file-level beforeEach only
    // reinstalls the implementation. Without this, the "nothing was written"
    // assertions below find the PREVIOUS test's fridge PUT and fail, and worse,
    // a genuinely broken no-write path would pass here for the same reason.
    mockedAuthFetch.mockClear();
  });

  function routeFetch(fridge: unknown[]) {
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/fridge') {
        return Promise.resolve({
          ok: true, status: 200, json: () => Promise.resolve(fridge),
        } as unknown as Response);
      }
      if (url.endsWith('/finish')) {
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve({
            status: 'finished', finished_at: new Date().toISOString(), returned_meals: 0,
          }),
        } as unknown as Response);
      }
      if (url.includes('/meals')) {
        return Promise.resolve({
          ok: true, status: 200, json: () => Promise.resolve([]),
        } as unknown as Response);
      }
      return Promise.resolve(okEmpty());
    });
  }

  /** The body of the PUT that persists the fridge, or undefined if none was issued. */
  function fridgePutBody(): { id: number; expiration_date: string | null }[] | undefined {
    const call = mockedAuthFetch.mock.calls.find(
      (args) => args[0] === '/fridge' && args[1]?.method === 'PUT',
    );
    return call ? JSON.parse(call[1].body) : undefined;
  }

  async function finishPlan(profile: Record<string, unknown>, fridge: unknown[]) {
    loginUser();
    mockedFetchProfile.mockResolvedValue({
      id: 1, email: 'test@test.com', country: null, language: 'English',
      measurement_system: 'metric', variability: 'traditional', include_spices: true,
      track_snacks: true, show_pieces: false, need_to_use_enabled: true,
      onboarding_completed: true, is_admin: false, default_day_layout: null,
      ...profile,
    });
    routeFetch(fridge);

    const user = userEvent.setup();
    render(
      <MealPlanner initialPlan={initialPlan} initialSummary={initialSummary} />,
      { wrapper: createWrapper() },
    );
    const finishBtn = await screen.findByRole('button', { name: /finish plan/i });
    await user.click(finishBtn);
    return user;
  }

  it('does not prompt when the waste preference is off', async () => {
    await finishPlan({ waste_tracking_enabled: false }, [EXPIRED, FRESH]);

    await waitFor(() => expect(screen.getByText(/finished plan/i)).toBeInTheDocument());
    expect(screen.queryByText(/anything past its date/i)).not.toBeInTheDocument();
  });

  it('does not prompt when nothing is past its date', async () => {
    await finishPlan({ waste_tracking_enabled: true }, [FRESH]);

    await waitFor(() => expect(screen.getByText(/finished plan/i)).toBeInTheDocument());
    expect(screen.queryByText(/anything past its date/i)).not.toBeInTheDocument();
  });

  it('lists only the expired items, and finishes the plan regardless', async () => {
    await finishPlan({ waste_tracking_enabled: true }, [EXPIRED, FRESH]);

    await screen.findByText(/anything past its date/i);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Yogurt')).toBeInTheDocument();
    // The in-date batch must not be dragged into a question about spoilage.
    expect(within(dialog).queryByText('Rice')).not.toBeInTheDocument();
    // The finish itself already landed server-side — the prompt is separate.
    expect(screen.getByText(/finished plan/i)).toBeInTheDocument();
  });

  it('bins an item: drops it from the fridge PUT and records it as waste', async () => {
    const user = await finishPlan({ waste_tracking_enabled: true }, [EXPIRED, FRESH]);
    await screen.findByText(/anything past its date/i);

    await user.click(screen.getByRole('radio', { name: /threw it out/i }));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      const sent = fridgePutBody();
      expect(sent).toBeDefined();
      expect(sent!.map((i: { id: number }) => i.id)).toEqual([FRESH.id]);
    });

    expect(mockedRecordWaste).toHaveBeenCalledWith([
      {
        name: 'Yogurt',
        quantity_grams: 500,
        expiration_date: EXPIRED.expiration_date,
        reason: 'thrown_out',
        source: 'finish_plan',
      },
    ]);
  });

  it('keeps a still-fine item, pushes its date a week, and STILL records it', async () => {
    const user = await finishPlan({ waste_tracking_enabled: true }, [EXPIRED, FRESH]);
    await screen.findByText(/anything past its date/i);

    await user.click(screen.getByRole('radio', { name: /still fine/i }));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      const sent = fridgePutBody();
      expect(sent).toBeDefined();
      // Item survives...
      expect(sent!.map((i: { id: number }) => i.id)).toEqual([EXPIRED.id, FRESH.id]);
      // ...with its date moved on a week from TODAY, not from the stale date.
      expect(sent![0].expiration_date).toBe(addDaysISO(todayISO(), 7));
      // The untouched batch is passed through unchanged.
      expect(sent![1].expiration_date).toBe(FRESH.expiration_date);
    });

    // still_fine is NOT waste, but it IS recorded — it is the denominator a
    // binned count has to be read against.
    expect(mockedRecordWaste).toHaveBeenCalledWith([
      expect.objectContaining({ reason: 'still_fine', source: 'finish_plan' }),
    ]);
  });

  it('writes nothing at all when the prompt is skipped', async () => {
    const user = await finishPlan({ waste_tracking_enabled: true }, [EXPIRED, FRESH]);
    await screen.findByText(/anything past its date/i);

    await user.click(screen.getByRole('radio', { name: /threw it out/i }));
    await user.click(screen.getByRole('button', { name: /^skip$/i }));

    await waitFor(() =>
      expect(screen.queryByText(/anything past its date/i)).not.toBeInTheDocument(),
    );
    expect(mockedRecordWaste).not.toHaveBeenCalled();
    expect(fridgePutBody()).toBeUndefined();
  });

  it('confirming with nothing answered touches neither the fridge nor the waste log', async () => {
    const user = await finishPlan({ waste_tracking_enabled: true }, [EXPIRED, FRESH]);
    await screen.findByText(/anything past its date/i);

    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.queryByText(/anything past its date/i)).not.toBeInTheDocument(),
    );
    expect(mockedRecordWaste).not.toHaveBeenCalled();
    expect(fridgePutBody()).toBeUndefined();
  });
});
