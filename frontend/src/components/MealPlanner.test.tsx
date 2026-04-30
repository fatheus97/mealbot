import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MealPlanner } from './MealPlanner';
import { AuthProvider } from '../contexts/AuthContext';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

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
    expect(screen.getByText('Diet Type:')).toBeInTheDocument();
    expect(screen.getByText('Meals per day:')).toBeInTheDocument();
    expect(screen.getByText('People count:')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate plan/i })).toBeInTheDocument();
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
            { name: 'Eggs', meal_type: 'breakfast', ingredients: [], steps: [] },
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
    await waitFor(() => expect(screen.getByText('Eggs')).toBeInTheDocument());

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
      days: [{ meals: [{ name: 'Eggs', meal_type: 'breakfast', ingredients: [], steps: [] }] }],
      shopping_list: [],
    };
    const initialSummary = {
      id: 60,
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
      id: 1, day_index: 1, meal_index: 1, name: 'Eggs',
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
      expect(screen.getByText('Eggs')).toBeInTheDocument();
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
      days: [{ meals: [{ name: 'Stew', meal_type: 'dinner', ingredients: [], steps: [] }] }],
      shopping_list: [],
    };
    const initialSummary = {
      id: 70,
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
      days: [{ meals: [{ name: 'Stew', meal_type: 'dinner', ingredients: [], steps: [] }] }],
      shopping_list: [],
    };
    const initialSummary = {
      id: 80, created_at: new Date().toISOString(), days: 1, meals_per_day: 1,
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
});
