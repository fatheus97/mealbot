import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PantryStaples } from './PantryStaples';
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

/** Route authFetch: GET /staples returns `initial`; PUT echoes its own body. */
function mockStaples(initial: { name: string }[]) {
  mockedAuthFetch.mockImplementation((url: string, opts?: { method?: string; body?: string }) => {
    if (url === '/staples' && (!opts || opts.method === undefined)) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(initial) });
    }
    if (url === '/staples' && opts?.method === 'PUT') {
      const body = JSON.parse(opts.body ?? '[]');
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
  });
}

function lastPutBody(): { name: string }[] | null {
  const put = [...mockedAuthFetch.mock.calls].reverse().find(
    (c) => c[0] === '/staples' && c[1]?.method === 'PUT',
  );
  return put ? JSON.parse(put[1].body) : null;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe('PantryStaples', () => {
  it('renders the staples list immediately (settings section, no expand step)', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }, { name: 'Olive Oil' }]);

    render(<PantryStaples />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());
    expect(screen.getByText('Olive Oil')).toBeInTheDocument();
    // The heading carries the count.
    expect(
      screen.getByRole('heading', { name: /pantry staples \(2\)/i }),
    ).toBeInTheDocument();
  });

  it('adds a staple and saves the full list', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }]);
    const user = userEvent.setup();

    render(<PantryStaples />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'Flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByText('Flour')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save staples/i }));

    await waitFor(() =>
      expect(lastPutBody()).toEqual([{ name: 'Salt' }, { name: 'Flour' }]),
    );
    // After a successful save the dirty hint is replaced by the saved notice.
    await waitFor(() => expect(screen.getByText('Saved')).toBeInTheDocument());
  });

  it('removes a staple and saves without it', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }, { name: 'Oil' }]);
    const user = userEvent.setup();

    render(<PantryStaples />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Remove Salt' }));
    expect(screen.queryByText('Salt')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save staples/i }));
    await waitFor(() => expect(lastPutBody()).toEqual([{ name: 'Oil' }]));
  });

  it('will not add a case-insensitive duplicate', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }]);
    const user = userEvent.setup();

    render(<PantryStaples />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'salt');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    // Still exactly one salt chip, and Save stays disabled (nothing changed).
    expect(screen.getAllByText(/^salt$/i)).toHaveLength(1);
    expect(screen.getByRole('button', { name: /save staples/i })).toBeDisabled();
  });
});
