import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Fridge } from './Fridge';
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

describe('Fridge', () => {
  it('shows "Please log in" when no userId', () => {
    render(<Fridge />, { wrapper: createWrapper() });
    expect(screen.getByText(/please log in/i)).toBeInTheDocument();
  });

  it('renders server items', async () => {
    loginUser();
    const items = [
      { name: 'Chicken', quantity_grams: 500, need_to_use: false },
      { name: 'Rice', quantity_grams: 1000, need_to_use: true },
    ];

    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(items),
    });

    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      const inputs = screen.getAllByPlaceholderText(/chicken breast/i);
      expect(inputs).toHaveLength(2);
    });

    // Verify the input values
    const nameInputs = screen.getAllByPlaceholderText(/chicken breast/i);
    expect(nameInputs[0]).toHaveValue('Chicken');
    expect(nameInputs[1]).toHaveValue('Rice');
  });

  it('adds a new item', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/fridge is empty/i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /add ingredient/i }));

    expect(screen.getAllByPlaceholderText(/chicken breast/i)).toHaveLength(1);
  });

  it('removes an item', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Milk', quantity_grams: 500, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Milk')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /remove/i }));

    expect(screen.queryByDisplayValue('Milk')).not.toBeInTheDocument();
  });

  it('filters empty names on save', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([
        { name: 'Eggs', quantity_grams: 200, need_to_use: false },
        { name: '', quantity_grams: 100, need_to_use: false },
      ]),
    });

    // Response for save
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Eggs', quantity_grams: 200, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Eggs')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save fridge/i }));

    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
        method: 'PUT',
        body: JSON.stringify([{ name: 'Eggs', quantity_grams: 200, need_to_use: false }]),
      });
    });
  });

  it('shows success notice after save', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Eggs', quantity_grams: 200, need_to_use: false }]),
    });

    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Eggs', quantity_grams: 200, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Eggs')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save fridge/i }));

    await waitFor(() => {
      expect(screen.getByText(/saved successfully/i)).toBeInTheDocument();
    });
  });

  it('shows error notice on save failure', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Eggs', quantity_grams: 200, need_to_use: false }]),
    });

    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Eggs')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save fridge/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to save/i)).toBeInTheDocument();
    });
  });
});
