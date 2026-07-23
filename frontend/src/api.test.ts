import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  authFetch,
  createInvite,
  fetchInvites,
  fetchUserProfile,
  redeemInvite,
  revokeInvite,
  updateUserProfile,
} from './api';

// Mirror api.ts's resolution so this test passes whether VITE_API_BASE is
// unset (CI: resolves to "/api") or set by docker-compose.override.yml.
const MOCK_BASE = import.meta.env.VITE_API_BASE ?? '/api';

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
  document.cookie = 'mealbot_csrf=; Path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
});

afterEach(() => {
  document.cookie = 'mealbot_csrf=; Path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
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
  it('always sends credentials: "include" so cookies travel with the request', async () => {
    mockFetch(200);
    await authFetch('/test');
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${MOCK_BASE}/test`);
    expect(call[1].credentials).toBe('include');
  });

  it('does NOT send Authorization header (cookie-based auth)', async () => {
    mockFetch(200);
    await authFetch('/test');
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].headers['Authorization']).toBeUndefined();
  });

  it('attaches X-CSRF-Token from cookie on POST', async () => {
    document.cookie = 'mealbot_csrf=tok-abc; Path=/';
    mockFetch(200);

    await authFetch('/users', { method: 'POST', body: JSON.stringify({}) });

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].headers['X-CSRF-Token']).toBe('tok-abc');
  });

  it('omits X-CSRF-Token on safe methods (GET/HEAD/OPTIONS)', async () => {
    document.cookie = 'mealbot_csrf=tok-abc; Path=/';
    mockFetch(200);

    await authFetch('/users');

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].headers['X-CSRF-Token']).toBeUndefined();
  });

  it('on 401 attempts /auth/refresh and retries the original request', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    // 1st: original 401 → 2nd: refresh 204 → 3rd: retried request 200
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 401, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: true, status: 204, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });

    const res = await authFetch('/users');
    expect(res.status).toBe(200);

    const calls = fetchMock.mock.calls;
    expect(calls).toHaveLength(3);
    expect(calls[0][0]).toBe(`${MOCK_BASE}/users`);
    expect(calls[1][0]).toBe(`${MOCK_BASE}/auth/refresh`);
    expect(calls[2][0]).toBe(`${MOCK_BASE}/users`);
  });

  it('on 401 from /auth/* does NOT recurse into refresh', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401, json: () => Promise.resolve({}) });

    const res = await authFetch('/auth/login', { method: 'POST', body: JSON.stringify({}) });
    expect(res.status).toBe(401);
    // Only the original call — no /auth/refresh attempt.
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it('dispatches mealbot:logout when refresh fails', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 401, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: false, status: 401, json: () => Promise.resolve({}) });

    const handler = vi.fn();
    window.addEventListener('mealbot:logout', handler);
    try {
      await authFetch('/users');
    } finally {
      window.removeEventListener('mealbot:logout', handler);
    }
    expect(handler).toHaveBeenCalled();
  });

  it('single-flight refresh: concurrent 401s share one /auth/refresh call', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    // For each of N concurrent calls: original 401 + retry 200. Plus one
    // shared /auth/refresh 204 in the middle.
    // We script it so the first two requests both 401, then one /auth/refresh
    // 204, then both retries succeed. With single-flight, this works; without,
    // there would be TWO refresh calls and the test would fail.
    fetchMock.mockImplementation((url: string) => {
      if (url.endsWith('/auth/refresh')) {
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve({}) });
      }
      // Track per-URL retry: first call 401, second call 200.
      if (!fetchMock.mock.results.some((r) =>
        (fetchMock.mock.calls[fetchMock.mock.results.indexOf(r)] as [string, RequestInit])[0] === url &&
        // Find matching prior 200 for same URL
        false
      )) {
        // Fallback simpler counter via closure below.
      }
      return null as never;
    });

    // Simpler: use a per-URL call counter.
    const counts: Record<string, number> = {};
    fetchMock.mockImplementation((url: string) => {
      counts[url] = (counts[url] ?? 0) + 1;
      if (url.endsWith('/auth/refresh')) {
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve({}) });
      }
      // First call to a non-auth URL = 401, subsequent = 200.
      if (counts[url] === 1) {
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    });

    const [r1, r2] = await Promise.all([authFetch('/a'), authFetch('/b')]);
    expect(r1.status).toBe(200);
    expect(r2.status).toBe(200);
    expect(counts[`${MOCK_BASE}/auth/refresh`]).toBe(1);
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
    // Two 401s so refresh fails and the original 401 surfaces unwrapped.
    mockFetch(403);

    await expect(fetchUserProfile()).rejects.toThrow('Profile fetch failed: 403');
  });
});

describe('updateUserProfile', () => {
  it('sends PATCH with body and CSRF header when cookie set', async () => {
    document.cookie = 'mealbot_csrf=patch-token; Path=/';
    const updated = { id: 1, country: 'US' };
    mockFetch(200, updated);

    await updateUserProfile({ country: 'US' });

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].method).toBe('PATCH');
    expect(JSON.parse(call[1].body)).toEqual({ country: 'US' });
    expect(call[1].headers['X-CSRF-Token']).toBe('patch-token');
  });

  it('throws on non-ok response', async () => {
    mockFetch(400);

    await expect(updateUserProfile({ country: 'US' })).rejects.toThrow(
      'Profile update failed: 400',
    );
  });
});

describe('admin invites', () => {
  it('createInvite POSTs and returns the minted link', async () => {
    const body = {
      id: 3,
      invite_url: 'http://localhost:5173/?invite=tok',
      expires_at: '2026-07-25T10:00:00Z',
      is_comped: true,
      note: null,
    };
    mockFetch(201, body);
    const res = await createInvite({ is_comped: true, expires_in_hours: 48 });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${MOCK_BASE}/admin/invites`);
    expect(call[1].method).toBe('POST');
    expect(res.invite_url).toBe('http://localhost:5173/?invite=tok');
  });

  it('fetchInvites GETs the list', async () => {
    mockFetch(200, { invites: [] });
    const res = await fetchInvites();
    expect(res.invites).toEqual([]);
  });

  it('revokeInvite surfaces the backend detail on 409', async () => {
    mockFetch(409, { detail: "This invite has already been used and can't be revoked." });
    await expect(revokeInvite(1)).rejects.toThrow(/already been used/i);
  });
});

describe('redeemInvite', () => {
  it('resolves on 201', async () => {
    mockFetch(201);
    await expect(redeemInvite('tok', 'a@b.com', 'GoodPass123')).resolves.toBeUndefined();
  });

  it('maps a 400 to the backend opaque detail', async () => {
    mockFetch(400, { detail: 'This invite link is invalid or has expired.' });
    await expect(redeemInvite('tok', 'a@b.com', 'GoodPass123')).rejects.toThrow(
      /invalid or has expired/i,
    );
  });

  it('maps a 409 to an email-taken message', async () => {
    mockFetch(409, { detail: 'Email already registered' });
    await expect(redeemInvite('tok', 'a@b.com', 'GoodPass123')).rejects.toThrow(
      /already registered/i,
    );
  });

  it('maps a 422 Pydantic list to the first message', async () => {
    mockFetch(422, { detail: [{ msg: 'Password must contain at least one digit' }] });
    await expect(redeemInvite('tok', 'a@b.com', 'weakpass')).rejects.toThrow(/at least one digit/i);
  });

  it('maps a 429 to a rate-limit message', async () => {
    mockFetch(429, {});
    await expect(redeemInvite('tok', 'a@b.com', 'GoodPass123')).rejects.toThrow(
      /too many attempts/i,
    );
  });
});
