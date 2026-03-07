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

    // Never resolve to keep mutation pending
    mockedAuthFetch.mockReturnValueOnce(new Promise(() => {}));

    const user = userEvent.setup();
    render(<MealPlanner />, { wrapper: createWrapper() });

    const button = screen.getByRole('button', { name: /generate plan/i });
    await user.click(button);

    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/generating/i);
  });

  it('shows error on generation failure', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Server error'),
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
              uses_existing_ingredients: [],
              ingredients: [{ name: 'Eggs', quantity_grams: 200 }],
              steps: ['Crack eggs', 'Cook'],
            },
          ],
        },
      ],
      shopping_list: [{ name: 'Eggs', quantity_grams: 200 }],
    };

    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(planResponse),
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

  it('regenerate sends correct frozen_meals', async () => {
    loginUser();

    const planResponse = {
      plan_id: 42,
      days: [
        {
          meals: [
            { name: 'Meal A', meal_type: 'breakfast', uses_existing_ingredients: [], ingredients: [], steps: [] },
            { name: 'Meal B', meal_type: 'lunch', uses_existing_ingredients: [], ingredients: [], steps: [] },
          ],
        },
      ],
      shopping_list: [],
    };

    // First call: generate
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(planResponse),
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

    // Second call: regenerate
    const regeneratedPlan = { ...planResponse, days: [{ meals: [planResponse.days[0].meals[0], { ...planResponse.days[0].meals[1], name: 'Meal C' }] }] };
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(regeneratedPlan),
    });

    await user.click(screen.getByRole('button', { name: /regenerate unfrozen/i }));

    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/42/regenerate', {
        method: 'POST',
        body: JSON.stringify({ frozen_meals: [{ day_index: 0, meal_index: 0 }] }),
      });
    });
  });
});
