import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { AuthProvider, useAuth } from './AuthContext';
import type { ReactNode } from 'react';

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
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

    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(loginResponse),
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
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({}),
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
