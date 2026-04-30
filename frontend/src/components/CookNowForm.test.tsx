import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CookNowForm } from './CookNowForm';
import { AuthProvider } from '../contexts/AuthContext';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  generateRecipe: vi.fn(),
  cookRecipe: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
  mergeFridgeItems: vi.fn(),
  scanReceipt: vi.fn(),
}));

import { authFetch, generateRecipe, cookRecipe } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedGenerate = generateRecipe as ReturnType<typeof vi.fn>;
const mockedCook = cookRecipe as ReturnType<typeof vi.fn>;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
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

const okEmpty = () =>
  ({ ok: true, status: 200, json: () => Promise.resolve({}) }) as unknown as Response;

beforeEach(() => {
  localStorage.clear();
  mockedAuthFetch.mockReset();
  mockedGenerate.mockReset();
  mockedCook.mockReset();
  // AuthProvider + useFridge hit authFetch; stub harmlessly.
  mockedAuthFetch.mockImplementation(() => Promise.resolve(okEmpty()));
});

describe('CookNowForm', () => {
  it('generates a recipe and displays it', async () => {
    loginUser();
    mockedGenerate.mockResolvedValueOnce({
      recipe: {
        name: 'Quick Soup',
        meal_type: 'soup',
        meal_type_label: 'Soup',
        ingredients: [{ name: 'chicken', quantity_grams: 200, is_spice: false }],
        steps: ['Simmer', 'Serve'],
        total_time_minutes: 20,
      },
    });

    render(<CookNowForm />, { wrapper: createWrapper() });

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/meal type/i), 'soup');
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /quick soup/i })).toBeInTheDocument(),
    );
    // slot_layout enforces the user-chosen meal_type on the backend.
    expect(mockedGenerate).toHaveBeenCalledTimes(1);
    const call = mockedGenerate.mock.calls[0][0];
    expect(call.meal_type).toBe('soup');
  });

  it('calls cookRecipe with the same request + recipe when Mark cooked is clicked', async () => {
    loginUser();
    mockedGenerate.mockResolvedValueOnce({
      recipe: {
        name: 'Quick Soup',
        meal_type: 'soup',
        meal_type_label: 'Soup',
        ingredients: [{ name: 'chicken', quantity_grams: 200, is_spice: false }],
        steps: ['Simmer'],
      },
    });
    mockedCook.mockResolvedValueOnce({
      id: 42,
      day_index: 1,
      meal_index: 1,
      name: 'Quick Soup',
      meal_type: 'soup',
      cooked_at: '2026-04-23T10:00:00Z',
      is_favorite: false,
    });

    render(<CookNowForm />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));
    await waitFor(() => screen.getByRole('button', { name: /mark as cooked/i }));

    await user.click(screen.getByRole('button', { name: /mark as cooked/i }));

    await waitFor(() => expect(mockedCook).toHaveBeenCalledTimes(1));
    const payload = mockedCook.mock.calls[0][0];
    expect(payload.meal_type).toBe('main_course');  // default
    expect(payload.recipe.name).toBe('Quick Soup');

    await waitFor(() => expect(screen.getByText(/✓ cooked/i)).toBeInTheDocument());
  });

  it('surfaces generation errors inline without clearing the form', async () => {
    loginUser();
    mockedGenerate.mockRejectedValueOnce(new Error('LLM down'));

    render(<CookNowForm />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/llm down/i),
    );
    // No recipe card rendered on error.
    expect(screen.queryByRole('button', { name: /mark as cooked/i })).toBeNull();
  });
});
