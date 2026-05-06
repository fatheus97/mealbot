import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './AuthContext';
import type { ReactNode } from 'react';

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

const okEmpty = () =>
  ({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve('{}'),
  }) as unknown as Response;

beforeEach(() => {
  // AuthProvider mounts and fires authFetch("/config") (and /users when a
  // localStorage hint exists). Default everything to a harmless ok-empty
  // response; specific tests override per URL.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okEmpty()));
  localStorage.clear();
});

describe('AuthContext bootstrap', () => {
  it('initializes userId from localStorage hint', () => {
    localStorage.setItem('mealbot_user_id', '42');
    localStorage.setItem('mealbot_user_email', 'test@x.com');

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.userId).toBe(42);
    expect(result.current.email).toBe('test@x.com');
  });

  it('returns null userId when localStorage is empty', () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.userId).toBeNull();
  });

  it('useAuth throws outside provider', () => {
    expect(() => renderHook(() => useAuth())).toThrow(
      'useAuth must be used within an AuthProvider',
    );
  });
});

describe('AuthContext login', () => {
  it('login posts JSON to /auth/login and stores profile from response', async () => {
    const profile = {
      id: 7,
      email: 'user@test.com',
      country: null,
      language: 'English',
      measurement_system: 'metric',
      variability: 'traditional',
      include_spices: true,
      track_snacks: true,
      onboarding_completed: true,
      is_demo: false,
      default_day_layout: null,
    };

    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes('/auth/login')) {
        // JSON body — verify shape
        expect(opts?.method).toBe('POST');
        expect(JSON.parse(opts?.body as string)).toEqual({
          email: 'user@test.com',
          password: 'pass',
        });
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(profile),
        });
      }
      return Promise.resolve(okEmpty());
    });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.login('user@test.com', 'pass');
    });

    expect(result.current.userId).toBe(7);
    expect(result.current.email).toBe('user@test.com');
    expect(result.current.onboardingCompleted).toBe(true);
    expect(localStorage.getItem('mealbot_user_id')).toBe('7');
    expect(localStorage.getItem('mealbot_user_email')).toBe('user@test.com');
    // No token written to localStorage anymore — cookie-only auth.
    expect(localStorage.getItem('mealbot_token')).toBeNull();
  });

  it('login throws on non-ok response', async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/auth/login')) {
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) });
      }
      return Promise.resolve(okEmpty());
    });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await expect(
      act(async () => {
        await result.current.login('bad@test.com', 'wrong');
      }),
    ).rejects.toThrow('Login failed');
  });
});

describe('AuthContext logout', () => {
  it('logout posts to /auth/logout and clears localStorage + state', async () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'a@b.com');
    localStorage.setItem('mealbot_onboarding', 'true');

    let logoutCalled = false;
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/auth/logout')) {
        logoutCalled = true;
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve({}) });
      }
      return Promise.resolve(okEmpty());
    });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.logout();
    });

    expect(logoutCalled).toBe(true);
    expect(result.current.userId).toBeNull();
    expect(result.current.email).toBe('');
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
    expect(localStorage.getItem('mealbot_user_email')).toBeNull();
    expect(localStorage.getItem('mealbot_onboarding')).toBeNull();
  });

  it('logout still clears local state when server call fails', async () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'a@b.com');

    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/auth/logout')) {
        return Promise.reject(new Error('network down'));
      }
      return Promise.resolve(okEmpty());
    });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.userId).toBeNull();
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
  });
});

describe('AuthContext misc', () => {
  it('setOnboardingCompleted persists flag', () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    act(() => {
      result.current.setOnboardingCompleted(true);
    });
    expect(result.current.onboardingCompleted).toBe(true);
    expect(localStorage.getItem('mealbot_onboarding')).toBe('true');

    act(() => {
      result.current.setOnboardingCompleted(false);
    });
    expect(result.current.onboardingCompleted).toBe(false);
    expect(localStorage.getItem('mealbot_onboarding')).toBeNull();
  });

  it('listens for mealbot:logout event and clears state without re-calling /auth/logout', async () => {
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'a@b.com');

    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    // Track whether /auth/logout was called by the listener — it must NOT be,
    // otherwise we'd loop back into the 401-refresh-dispatch cycle.
    fetchMock.mockImplementation((url: string) => {
      if (url.includes('/auth/logout')) {
        // Make this loud so the test fails if we ever wire the listener wrong.
        throw new Error('listener should not call /auth/logout');
      }
      return Promise.resolve(okEmpty());
    });

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.userId).toBe(1);

    act(() => {
      window.dispatchEvent(new Event('mealbot:logout'));
    });

    await waitFor(() => {
      expect(result.current.userId).toBeNull();
    });
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
  });
});
