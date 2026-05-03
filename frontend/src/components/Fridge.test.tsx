import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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

  it('renders server items as read-only text', async () => {
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
      expect(screen.getByText('Chicken')).toBeInTheDocument();
    });

    expect(screen.getByText('Rice')).toBeInTheDocument();
  });

  it('adds a new item via modal and auto-saves', async () => {
    loginUser();
    // Load empty fridge
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });
    // Response for auto-save PUT
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Butter', quantity_grams: 100, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/fridge is empty/i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /add ingredient/i }));
    expect(screen.getByText('Add Ingredient')).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/chicken breast/i), 'Butter');
    await user.click(screen.getByRole('button', { name: /ok/i }));

    expect(screen.getByText('Butter')).toBeInTheDocument();

    // Verify auto-save PUT was called
    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
        method: 'PUT',
        body: JSON.stringify([{ name: 'Butter', quantity_grams: 100, need_to_use: false, expiration_date: null }]),
      });
    });
  });

  it('removes an item via confirm dialog and auto-saves', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Milk', quantity_grams: 500, need_to_use: false }]),
    });
    // Response for auto-save PUT (empty fridge after removal)
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Milk')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Remove' }));

    // Confirm dialog appears with item context, fridge state unchanged.
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/Remove "Milk"/)).toBeInTheDocument();
    expect(screen.getByText('Milk')).toBeInTheDocument();

    // Confirm removal — dialog has its own "Remove" button.
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    expect(screen.queryByText('Milk')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Verify auto-save PUT was called with empty array
    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
        method: 'PUT',
        body: JSON.stringify([]),
      });
    });
  });

  it('cancels remove without mutating state', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Milk', quantity_grams: 500, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Milk')).toBeInTheDocument();
    });

    // Snapshot call count before cancel so we can assert no NEW fetches —
    // mockedAuthFetch isn't reset between tests in this file.
    const callsBefore = mockedAuthFetch.mock.calls.length;

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Milk')).toBeInTheDocument();
    // Cancel must not trigger any further fetches (no auto-save PUT).
    expect(mockedAuthFetch.mock.calls.length).toBe(callsBefore);
  });

  it('shows error notice on auto-save failure after confirmed remove', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Eggs', quantity_grams: 200, need_to_use: false }]),
    });

    // Auto-save PUT fails
    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Eggs')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      expect(screen.getByText(/failed to save/i)).toBeInTheDocument();
    });
  });

  it('edits an existing item via modal and auto-saves', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Milk', quantity_grams: 500, need_to_use: false }]),
    });
    // Response for auto-save PUT
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Cream', quantity_grams: 500, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Milk')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /edit/i }));

    expect(screen.getByText('Edit Ingredient')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Milk')).toBeInTheDocument();

    const nameInput = screen.getByDisplayValue('Milk');
    await user.clear(nameInput);
    await user.type(nameInput, 'Cream');
    await user.click(screen.getByRole('button', { name: /ok/i }));

    expect(screen.getByText('Cream')).toBeInTheDocument();
    expect(screen.queryByText('Milk')).not.toBeInTheDocument();

    // Verify auto-save PUT was called
    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
        method: 'PUT',
        body: JSON.stringify([{ name: 'Cream', quantity_grams: 500, need_to_use: false, expiration_date: null }]),
      });
    });
  });
});
