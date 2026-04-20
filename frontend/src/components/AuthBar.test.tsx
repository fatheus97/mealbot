import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthBar } from './AuthBar';
import { AuthProvider } from '../contexts/AuthContext';
import { usePreferencesStore, DEFAULT_PREFERENCES } from '../store/usePreferencesStore';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

function createWrapper(queryClient?: QueryClient) {
  const client =
    queryClient ??
    new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

// AuthProvider mounts and calls authFetch("/config") to gate the Try Demo
// button. Route by URL so /config gets a harmless ok response and tests can
// stub the endpoint they actually care about without queue ordering games.
const okEmpty = () =>
  ({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
  }) as unknown as Response;

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn());
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url === '/config') return Promise.resolve(okEmpty());
    return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
  });
});

describe('AuthBar', () => {
  it('renders login form by default', () => {
    render(<AuthBar />, { wrapper: createWrapper() });

    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Email')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('calls login on sign in', async () => {
    const loginResponse = {
      access_token: 'jwt',
      token_type: 'bearer',
      user_id: 1,
      email: 'test@x.com',
      onboarding_completed: false,
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users/login') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(loginResponse),
        } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.type(screen.getByPlaceholderText('Email'), 'test@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'password123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(localStorage.getItem('mealbot_token')).toBe('jwt');
    });
  });

  it('shows email and logout when logged in', () => {
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    render(<AuthBar />, { wrapper: createWrapper() });

    expect(screen.getByText('Welcome')).toBeInTheDocument();
    expect(screen.getByText(/user@test.com/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });

  it('logout clears state', async () => {
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(localStorage.getItem('mealbot_token')).toBeNull();
  });

  it('logout clears query cache and resets persisted preferences (cross-account leak guard)', async () => {
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user-a@test.com');

    // Seed user-A preferences (would otherwise persist into user-B's session).
    usePreferencesStore.getState().setDietType('vegan');
    usePreferencesStore.getState().setTastePreferences('private taste notes');
    usePreferencesStore.getState().setAvoidIngredients('peanuts');

    // Seed query cache with user-A's plan list.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    queryClient.setQueryData(['planList', 1], [{ id: 99, label: 'A secret plan' }]);
    expect(queryClient.getQueryData(['planList', 1])).toBeDefined();

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper(queryClient) });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    const prefs = usePreferencesStore.getState();
    expect(prefs.dietType).toBe(DEFAULT_PREFERENCES.dietType);
    expect(prefs.tastePreferences).toBe(DEFAULT_PREFERENCES.tastePreferences);
    expect(prefs.avoidIngredients).toBe(DEFAULT_PREFERENCES.avoidIngredients);
    expect(localStorage.getItem('mealbot-preferences')).toBeNull();
    expect(queryClient.getQueryData(['planList', 1])).toBeUndefined();
  });
});
