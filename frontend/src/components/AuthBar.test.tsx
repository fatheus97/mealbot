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
  // Call history accumulates across tests unless cleared — tests that assert
  // on mock.calls need a clean slate.
  mockedAuthFetch.mockClear();
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

  it('logout POSTs to /users/logout for server-side token revocation', async () => {
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users/logout') {
        return Promise.resolve({ ok: true, status: 204 } as unknown as Response);
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    const logoutCalls = mockedAuthFetch.mock.calls.filter(
      (c) => c[0] === '/users/logout',
    );
    expect(logoutCalls).toHaveLength(1);
    expect(logoutCalls[0][1]).toMatchObject({ method: 'POST' });
    expect(localStorage.getItem('mealbot_token')).toBeNull();
  });

  it('logout still clears local state when server revocation call fails', async () => {
    // The server call is best-effort: network failure must not trap a user
    // in a "logged in" state locally.
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'user@test.com');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users/logout') {
        return Promise.reject(new Error('network down'));
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /logout/i }));

    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(localStorage.getItem('mealbot_token')).toBeNull();
  });

  it('hides Register button when registration_enabled=false', async () => {
    // Default /config mock in beforeEach returns {} — no registration_enabled.
    render(<AuthBar />, { wrapper: createWrapper() });

    // Still render the login inputs so we don't confuse the assertion.
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Email')).toBeInTheDocument();
    });
    expect(
      screen.queryByRole('button', { name: /^register$/i }),
    ).not.toBeInTheDocument();
  });

  it('shows Register button when registration_enabled=true and auto-logs in after register', async () => {
    const loginResponse = {
      access_token: 'jwt-reg',
      token_type: 'bearer',
      user_id: 9,
      email: 'new@x.com',
      onboarding_completed: false,
    };

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ registration_enabled: true }),
        } as unknown as Response);
      }
      if (url === '/users/register') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: () => Promise.resolve({ message: 'Registered' }),
        } as unknown as Response);
      }
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

    const registerBtn = await screen.findByRole('button', { name: /^register$/i });

    await user.type(screen.getByPlaceholderText('Email'), 'new@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'correct-horse');
    await user.click(registerBtn);

    await waitFor(() => {
      expect(localStorage.getItem('mealbot_token')).toBe('jwt-reg');
    });

    const callUrls = mockedAuthFetch.mock.calls.map((c) => c[0] as string);
    expect(callUrls).toContain('/users/register');
    expect(callUrls).toContain('/users/login');
  });

  it('shows "account created" message when registration succeeds but auto-login fails', async () => {
    // The account was created but the follow-up /users/login got throttled
    // or 5xx'd. The user must NOT see "registration failed" — they'd try
    // again and hit a 409 on the duplicate email.
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ registration_enabled: true }),
        } as unknown as Response);
      }
      if (url === '/users/register') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: () => Promise.resolve({ message: 'Registered' }),
        } as unknown as Response);
      }
      if (url === '/users/login') {
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
    // No token — the login phase failed.
    expect(localStorage.getItem('mealbot_token')).toBeNull();
  });

  it('clears authError on next input change (stale-error UX guard)', async () => {
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users/login') {
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

    // Error shows.
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    // User fixes the typo — the stale error should disappear as soon as
    // they touch an input, not linger until the next submit.
    await user.type(screen.getByPlaceholderText('Password'), 'x');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('hides closed-alpha notice until /config resolves (no flash)', async () => {
    // Deployments with registration_enabled=true must not briefly render
    // the "closed alpha" notice during the /config round-trip. Initial
    // state is null, so neither "Register" button nor the notice render
    // until we know which one is correct.
    let resolveConfig: (r: unknown) => void = () => {};
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') {
        return new Promise((res) => {
          resolveConfig = res;
        });
      }
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    render(<AuthBar />, { wrapper: createWrapper() });

    // /config is in-flight — neither banner nor Register button visible.
    expect(screen.queryByText(/closed alpha/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /^register$/i }),
    ).not.toBeInTheDocument();

    resolveConfig({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ registration_enabled: true }),
    });

    // Register button appears; closed-alpha notice never did.
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
    expect(localStorage.getItem('mealbot_token')).toBeNull();
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
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    const user = userEvent.setup();
    render(<AuthBar />, { wrapper: createWrapper() });

    await user.type(screen.getByPlaceholderText('Email'), 'new@x.com');
    await user.type(screen.getByPlaceholderText('Password'), 'short');
    await user.click(await screen.findByRole('button', { name: /^register$/i }));

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toMatch(/at least 8/i);
    // No /users/register call should have fired — the guard short-circuits.
    const registerCalls = mockedAuthFetch.mock.calls.filter(
      (c) => c[0] === '/users/register',
    );
    expect(registerCalls).toHaveLength(0);
  });

  it('shows inline error on login failure (no window.alert)', async () => {
    // A login failure must surface via an accessible inline banner, not a
    // blocking window.alert dialog. Regression guard — the component used
    // to call alert() which is a screen-reader antipattern and traps the
    // user until dismissed.
    const alertSpy = vi.spyOn(window, 'alert');

    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/config') return Promise.resolve(okEmpty());
      if (url === '/users/login') {
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
      if (url === '/demo/session') {
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
