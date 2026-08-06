import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Fridge } from './Fridge';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import { AuthProvider } from '../contexts/AuthContext';
import { setMobileViewport } from '../test/test-utils';
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
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it('leaves no untranslated English when switched to Czech (logged out)', () => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    const { container } = render(<Fridge />, { wrapper: createWrapper() });
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });

  it('leaves no untranslated English with items, on desktop AND mobile', async () => {
    // The logged-out case above renders two strings. Everything else — the
    // table headers, the sort chips, the cards, the batch counts, the
    // use-soon badge — needs a populated fridge, and the desktop table and
    // the mobile cards are entirely separate JSX branches.
    for (const mobile of [false, true]) {
      loginUser();
      setMobileViewport(mobile);
      useLocaleStore.setState({ locale: 'cs', explicit: true });
      mockedAuthFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve([
            { name: 'Kuřecí maso', quantity_grams: 500, need_to_use: false },
            // Two batches of the same name exercise the group row + plural.
            { name: 'Rýže', quantity_grams: 1000, need_to_use: true, expiration_date: '2026-09-01' },
            { name: 'Rýže', quantity_grams: 400, need_to_use: false, expiration_date: '2026-10-01' },
          ]),
      });

      const { container, unmount } = render(<Fridge />, { wrapper: createWrapper() });
      await waitFor(() => expect(screen.getByText('Kuřecí maso')).toBeInTheDocument());
      expect(untranslatedEnglishIn(container)).toEqual([]);
      unmount();
      localStorage.clear();
    }
  });

  it('shows "Please log in" when no userId', () => {
    render(<Fridge />, { wrapper: createWrapper() });
    expect(screen.getByText(/please log in/i)).toBeInTheDocument();
  });

  it('renders items as cards (not a table) on a mobile viewport', async () => {
    loginUser();
    setMobileViewport(true);
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve([
          { name: 'Chicken', quantity_grams: 500, need_to_use: false },
          { name: 'Rice', quantity_grams: 1000, need_to_use: true },
        ]),
    });

    render(<Fridge />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Chicken')).toBeInTheDocument());

    // Mobile branch: the 5-col table is replaced by cards + sort chips.
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Name/ })).toBeInTheDocument();
    // Each item is a card with its own Edit/Remove (still wired to the same handlers).
    expect(screen.getAllByRole('button', { name: /^Edit$/ })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /^Remove$/ })).toHaveLength(2);
    // need_to_use item surfaces the "use soon" badge.
    expect(screen.getByText(/use soon/i)).toBeInTheDocument();
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
