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

const okEmpty = () =>
  ({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
  }) as unknown as Response;

const profile = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  email: 'test@x.com',
  country: null,
  language: 'English',
  measurement_system: 'metric',
  variability: 'traditional',
  include_spices: true,
  track_snacks: true,
  onboarding_completed: false,
  is_demo: false,
  default_day_layout: null,
  ...overrides,
});

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn());
  localStorage.clear();
  mockedAuthFetch.mockClear();
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url === '/config') return Promise.resolve(okEmpty());
    if (url === '/users') return Promise.resolve(okEmpty());
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
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/login') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(profile({ id: 1, email: 'test@x.com' })),
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
      expect(localStorage.getItem('mealbot_user_id')).toBe('1');
    });
  });

  it('shows email and logout when logged in (localStorage hint)', () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    render(<AuthBar />, { wrapper: createWrapper() });

    expect(screen.getByText('Welcome')).toBeInTheDocument();
    expect(screen.getByText(/user@test.com/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });

  it('logout clears state', async () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/logout') {
        return Promise.resolve({ ok: true, status: 204 } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    await waitFor(() => {
      expect(screen.getByText('Login')).toBeInTheDocument();
    });
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
  });

  it('logout POSTs to /auth/logout for server-side session revocation', async () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/logout') {
        return Promise.resolve({ ok: true, status: 204 } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    const logoutCalls = mockedAuthFetch.mock.calls.filter(
      (c) => c[0] === '/auth/logout',
    );
    expect(logoutCalls).toHaveLength(1);
    expect(logoutCalls[0][1]).toMatchObject({ method: 'POST' });
    await waitFor(() => {
      expect(localStorage.getItem('mealbot_user_id')).toBeNull();
    });
  });

  it('logout still clears local state when server revocation call fails', async () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/logout') {
        return Promise.reject(new Error('network down'));
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    await waitFor(() => {
      expect(screen.getByText('Login')).toBeInTheDocument();
    });
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
  });

  it('hides Register button when registration_enabled=false', async () => {
    render(<AuthBar />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Email')).toBeInTheDocument();
    });
    expect(
      screen.queryByRole('button', { name: /^register$/i }),
    ).not.toBeInTheDocument();
  });

  it('shows Register button when registration_enabled=true and auto-logs in after register', async () => {
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ registration_enabled: true }),
        } as unknown as Response);
      }
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/users/register') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: () => Promise.resolve({ message: 'Registered' }),
        } as unknown as Response);
      }
      if (url === '/auth/login') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(profile({ id: 9, email: 'new@x.com' })),
        } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    const registerBtn = await screen.findByRole('button', { name: /^register$/i });

    await user.type(screen.getByPlaceholderText('Email'), 'new@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'correct-horse');
    await user.click(registerBtn);

    await waitFor(() => {
      expect(localStorage.getItem('mealbot_user_id')).toBe('9');
    });

    const callUrls = mockedAuthFetch.mock.calls.map((c) => c[0] as string);
    expect(callUrls).toContain('/users/register');
    expect(callUrls).toContain('/auth/login');
  });

  it('shows "account created" message when registration succeeds but auto-login fails', async () => {
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ registration_enabled: true }),
        } as unknown as Response);
      }
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/users/register') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: () => Promise.resolve({ message: 'Registered' }),
        } as unknown as Response);
      }
      if (url === '/auth/login') {
        return Promise.resolve({
          ok: false,
          status: 429,
          json: () => Promise.resolve({}),
        } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.type(screen.getByPlaceholderText('Email'), 'new@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'correct-horse');
    await user.click(await screen.findByRole('button', { name: /^register$/i }));

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toMatch(/account created/i);
    // No userId — the login phase failed.
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
  });

  it('clears authError on next input change (stale-error UX guard)', async () => {
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/login') {
        return Promise.resolve({
          ok: false,
          status: 401,
          json: () => Promise.resolve({}),
        } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.type(screen.getByPlaceholderText('Email'), 'bad@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText('Password'), 'x');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('hides closed-alpha notice until /config resolves (no flash)', async () => {
    let resolveConfig: (r: unknown) => void = () => {};
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return new Promise((res) => {
          resolveConfig = res;
        });
      }
      if (url === '/users') return Promise.resolve(okEmpty());
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    render(<AuthBar />, { wrapper: createWrapper() });

    expect(screen.queryByText(/closed alpha/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /^register$/i }),
    ).not.toBeInTheDocument();

    resolveConfig({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ registration_enabled: true }),
    });

    expect(
      await screen.findByRole('button', { name: /^register$/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/closed alpha/i)).not.toBeInTheDocument();
  });

  it('shows inline error when register fails and does not log in', async () => {
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ registration_enabled: true }),
        } as unknown as Response);
      }
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/users/register') {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: () => Promise.resolve({ detail: 'email taken' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.type(screen.getByPlaceholderText('Email'), 'dup@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'correct-horse');
    await user.click(await screen.findByRole('button', { name: /^register$/i }));

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toMatch(/registration failed/i);
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
  });

  it('blocks short-password register client-side before hitting the backend', async () => {
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ registration_enabled: true }),
        } as unknown as Response);
      }
      if (url === '/users') return Promise.resolve(okEmpty());
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.type(screen.getByPlaceholderText('Email'), 'new@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'short');
    await user.click(await screen.findByRole('button', { name: /^register$/i }));

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toMatch(/at least 8/i);
    const registerCalls = mockedAuthFetch.mock.calls.filter(
      (c) => c[0] === '/users/register',
    );
    expect(registerCalls).toHaveLength(0);
  });

  it('shows inline error on login failure (no window.alert)', async () => {
    const alertSpy = vi.spyOn(window, 'alert');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/login') {
        return Promise.resolve({
          ok: false,
          status: 401,
          json: () => Promise.resolve({ detail: 'bad' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.type(screen.getByPlaceholderText('Email'), 'bad@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toBe('Login failed. Check your credentials.');
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('shows inline error when Try Demo fails', async () => {
    const alertSpy = vi.spyOn(window, 'alert');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ demo_mode: true }),
        } as unknown as Response);
      }
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/demo') {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: () => Promise.resolve({}),
        } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    const demoBtn = await screen.findByRole('button', { name: /try demo/i });
    await user.click(demoBtn);

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toBe('Demo unavailable. Please try again.');
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('logout clears query cache and resets persisted preferences (cross-account leak guard)', async () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user-a@test.com');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users') return Promise.resolve(okEmpty());
      if (url === '/auth/logout') {
        return Promise.resolve({ ok: true, status: 204 } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    usePreferencesStore.getState().setDietType('vegan');
    usePreferencesStore.getState().setTastePreferences('private taste notes');
    usePreferencesStore.getState().setAvoidIngredients('peanuts');

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    queryClient.setQueryData(['planList', 1], [{ id: 99, label: 'A secret plan' }]);
    expect(queryClient.getQueryData(['planList', 1])).toBeDefined();

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper(queryClient) });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    await waitFor(() => {
      const prefs = usePreferencesStore.getState();
      expect(prefs.dietType).toBe(DEFAULT_PREFERENCES.dietType);
    });
    const prefs = usePreferencesStore.getState();
    expect(prefs.tastePreferences).toBe(DEFAULT_PREFERENCES.tastePreferences);
    expect(prefs.avoidIngredients).toBe(DEFAULT_PREFERENCES.avoidIngredients);
    expect(localStorage.getItem('mealbot-preferences')).toBeNull();
    expect(queryClient.getQueryData(['planList', 1])).toBeUndefined();
  });
});
