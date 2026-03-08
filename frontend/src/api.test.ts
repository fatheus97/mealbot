import { describe, it, expect, vi, beforeEach } from 'vitest';
import { authFetch, fetchUserProfile, updateUserProfile } from './api';

const MOCK_BASE = 'http://localhost:8000/api';

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

function mockFetch(status: number, body: unknown = {}) {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

describe('authFetch', () => {
  it('attaches Authorization header when token exists', async () => {
    localStorage.setItem('mealbot_token', 'test-jwt');
    mockFetch(200);

    await authFetch('/test');

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${MOCK_BASE}/test`);
    expect(call[1].headers['Authorization']).toBe('Bearer test-jwt');
  });

  it('omits Authorization header when no token', async () => {
    mockFetch(200);

    await authFetch('/test');

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].headers['Authorization']).toBeUndefined();
  });

  it('clears localStorage and dispatches mealbot:logout on 401', async () => {
    localStorage.setItem('mealbot_token', 'expired');
    localStorage.setItem('mealbot_user_id', '1');
    localStorage.setItem('mealbot_user_email', 'a@b.com');
    mockFetch(401);

    const logoutHandler = vi.fn();
    window.addEventListener('mealbot:logout', logoutHandler);

    await authFetch('/test');

    expect(localStorage.getItem('mealbot_token')).toBeNull();
    expect(localStorage.getItem('mealbot_user_id')).toBeNull();
    expect(localStorage.getItem('mealbot_user_email')).toBeNull();
    expect(logoutHandler).toHaveBeenCalled();

    window.removeEventListener('mealbot:logout', logoutHandler);
  });

  it('returns response for non-401 errors without clearing storage', async () => {
    localStorage.setItem('mealbot_token', 'valid');
    mockFetch(500);

    const res = await authFetch('/test');

    expect(res.status).toBe(500);
    expect(localStorage.getItem('mealbot_token')).toBe('valid');
  });

  it('sets Content-Type to application/json by default', async () => {
    mockFetch(200);

    await authFetch('/test');

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].headers['Content-Type']).toBe('application/json');
  });

  it('allows overriding headers', async () => {
    mockFetch(200);

    await authFetch('/test', {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].headers['Content-Type']).toBe('application/x-www-form-urlencoded');
  });
});

describe('fetchUserProfile', () => {
  it('returns parsed JSON on success', async () => {
    const profile = { id: 1, email: 'a@b.com', country: null };
    mockFetch(200, profile);

    const result = await fetchUserProfile();

    expect(result).toEqual(profile);
  });

  it('throws on non-ok response', async () => {
    mockFetch(403);

    await expect(fetchUserProfile()).rejects.toThrow('Profile fetch failed: 403');
  });
});

describe('updateUserProfile', () => {
  it('sends PATCH with body', async () => {
    const updated = { id: 1, country: 'US' };
    mockFetch(200, updated);

    await updateUserProfile({ country: 'US' });

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].method).toBe('PATCH');
    expect(JSON.parse(call[1].body)).toEqual({ country: 'US' });
  });

  it('throws on non-ok response', async () => {
    mockFetch(400);

    await expect(updateUserProfile({ country: 'US' })).rejects.toThrow(
      'Profile update failed: 400',
    );
  });
});
