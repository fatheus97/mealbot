import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
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

// AuthProvider mounts and fires a fetch to /api/config to gate the Try Demo
// button. Default that call to a harmless empty-body ok response so tests that
// don't care about /config don't need to set it up. Tests that care about
// specific endpoints override via mockImplementation or mockResolvedValueOnce.
const okEmpty = () =>
  ({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve('{}'),
  }) as unknown as Response;

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okEmpty()));
});

describe('AuthContext', () => {
  it('initializes userId from localStorage', () => {
    localStorage.setItem('mealbot_user_id', '42');
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_email', 'test@x.com');

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.userId).toBe(42);
    expect(result.current.token).toBe('tok');
    expect(result.current.email).toBe('test@x.com');
  });

  it('returns null userId when localStorage empty', () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.userId).toBeNull();
    expect(result.current.token).toBeNull();
  });

  it('login saves token/userId/email to localStorage and state', async () => {
    const loginResponse = {
      access_token: 'jwt-123',
      token_type: 'bearer',
      user_id: 7,
      email: 'user@test.com',
      onboarding_completed: true,
    };

    // Route fetches by URL: /config (from AuthProvider mount) gets an empty
    // ok response, /users/login gets the specific login payload. Can't use
    // mockResolvedValueOnce because mount + login fire in order and the
    // queue would be consumed in the wrong order.
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/users/login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(loginResponse),
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
    expect(localStorage.getItem('mealbot_token')).toBe('jwt-123');
    expect(localStorage.getItem('mealbot_user_id')).toBe('7');
  });

  it('login throws on non-ok response', async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/users/login')) {
        return Promise.resolve({
          ok: false,
          status: 401,
          json: () => Promise.resolve({}),
        });
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

  it('logout clears localStorage and resets state', async () => {
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'a@b.com');
    localStorage.setItem('mealbot_onboarding', 'true');

    const { result } = renderHook(() => useAuth(), { wrapper });

    act(() => {
      result.current.logout();
    });

    expect(result.current.userId).toBeNull();
    expect(result.current.email).toBe('');
    expect(localStorage.getItem('mealbot_token')).toBeNull();
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
    expect(localStorage.getItem('mealbot_onboarding')).toBeNull();
  });

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

  it('listens for mealbot:logout event and clears state', () => {
    localStorage.setItem('mealbot_token', 'tok');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'a@b.com');

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.userId).toBe(1);

    act(() => {
      window.dispatchEvent(new Event('mealbot:logout'));
    });

    expect(result.current.userId).toBeNull();
    expect(result.current.token).toBeNull();
    expect(localStorage.getItem('mealbot_token')).toBeNull();
  });

  it('useAuth throws outside provider', () => {
    expect(() => {
      renderHook(() => useAuth());
    }).toThrow('useAuth must be used within an AuthProvider');
  });
});
