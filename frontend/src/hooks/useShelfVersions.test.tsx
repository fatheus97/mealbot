// Household PR 4b: the fridge and staples version tokens on the client.
// The server side (409 on a stale token) is backend/tests/test_shelf_versions.py.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { ShelfChangedError, useFridge, useUpdateFridge, useUpdateStaples } from './useServerState';
import type { StockItem } from '../types';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

const MILK: StockItem = { id: 1, name: 'Milk', quantity_grams: 500, need_to_use: false };
const EGGS: StockItem = { id: 2, name: 'Eggs', quantity_grams: 300, need_to_use: false };
const REFUSED = 'The fridge was changed on another device, so your change wasn\'t saved.';

function reply(body: unknown, { status = 200, token }: { status?: number; token?: string } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(token ? { 'X-Fridge-Version': token } : {}),
    json: () => Promise.resolve(body),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

const puts = () => mockedAuthFetch.mock.calls.filter((c) => c[1]?.method === 'PUT');
const gets = () => mockedAuthFetch.mock.calls.filter((c) => c[0] === '/fridge' && !c[1]);
const sentToken = (call: unknown[]) =>
  (call[1] as { headers?: Record<string, string> }).headers?.['X-Fridge-Version'];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('fridge version token', () => {
  it('keeps the token beside the list, and components see only the list', async () => {
    mockedAuthFetch.mockResolvedValueOnce(reply([MILK], { token: '7:3' }));
    const { queryClient, wrapper } = setup();

    const { result } = renderHook(() => useFridge(1), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([MILK]);
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK], token: '7:3' });
  });

  it('sends the cached token and keeps the one the save got back', async () => {
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(['fridge', 1], { items: [MILK], token: '7:3' });
    mockedAuthFetch.mockResolvedValueOnce(reply([MILK, EGGS], { token: '7:4' }));

    const { result } = renderHook(() => useUpdateFridge(), { wrapper });
    result.current.mutate({ userId: 1, items: [MILK, EGGS] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
      method: 'PUT',
      body: JSON.stringify([MILK, EGGS]),
      headers: { 'X-Fridge-Version': '7:3' },
    });
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK, EGGS], token: '7:4' });
  });

  it('two quick saves: the second waits for the first and sends its token', async () => {
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(['fridge', 1], { items: [], token: '7:3' });
    const first = deferred<ReturnType<typeof reply>>();
    mockedAuthFetch
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(reply([MILK, EGGS], { token: '7:5' }));

    const { result } = renderHook(() => ({ a: useUpdateFridge(), b: useUpdateFridge() }), { wrapper });
    result.current.a.mutate({ userId: 1, items: [MILK] });
    result.current.b.mutate({ userId: 1, items: [MILK, EGGS] });

    // The second has not gone out while the first is in flight.
    await waitFor(() => expect(puts()).toHaveLength(1));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(puts()).toHaveLength(1);

    first.resolve(reply([MILK], { token: '7:4' }));
    // While the second is still queued, the first's answer moves only the
    // token: its list lacks the second edit, which is already on screen.
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(sentToken(puts()[0])).toBe('7:3');
    expect(sentToken(puts()[1])).toBe('7:4');
    await waitFor(() => expect(result.current.b.isSuccess).toBe(true));
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK, EGGS], token: '7:5' });
  });

  it('a 409 throws the server sentence, reloads, and refuses the save queued behind it', async () => {
    const { queryClient, wrapper } = setup();
    const first = deferred<ReturnType<typeof reply>>();
    mockedAuthFetch.mockImplementation((_url: string, opts?: { method?: string }) => {
      if (opts?.method === 'PUT') {
        return puts().length === 1 ? first.promise : Promise.resolve(reply([EGGS], { token: '7:9' }));
      }
      return Promise.resolve(reply([EGGS], { token: '7:8' }));
    });

    const { result } = renderHook(
      () => ({ list: useFridge(1), a: useUpdateFridge(), b: useUpdateFridge() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
    queryClient.setQueryData(['fridge', 1], { items: [MILK], token: '7:3' });

    result.current.a.mutate({ userId: 1, items: [MILK, EGGS] });
    result.current.b.mutate({ userId: 1, items: [] });
    await waitFor(() => expect(puts()).toHaveLength(1));

    first.resolve(reply({ detail: REFUSED }, { status: 409 }));

    await waitFor(() => expect(result.current.a.isError).toBe(true));
    expect(result.current.a.error).toBeInstanceOf(ShelfChangedError);
    expect(result.current.a.error?.message).toBe(REFUSED);
    // Reloaded: the partner's list and token are what the cache now holds.
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [EGGS], token: '7:8' });
    // The queued save was made from the old list: refused, never sent.
    await waitFor(() => expect(result.current.b.isError).toBe(true));
    expect(result.current.b.error).toBeInstanceOf(ShelfChangedError);
    expect(puts()).toHaveLength(1);

    // A save made after the reload is good and carries the reloaded token.
    result.current.a.mutate({ userId: 1, items: [EGGS, MILK] });
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(sentToken(puts()[1])).toBe('7:8');
  });

  it('no token known: the PUT carries no header at all', async () => {
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(['fridge', 1], { items: [MILK], token: null });
    mockedAuthFetch.mockResolvedValueOnce(reply([MILK]));

    const { result } = renderHook(() => useUpdateFridge(), { wrapper });
    result.current.mutate({ userId: 1, items: [MILK] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
      method: 'PUT',
      body: JSON.stringify([MILK]),
    });
  });

  it('refetches on focus, but not while a save of ours is pending', async () => {
    mockedAuthFetch.mockResolvedValueOnce(reply([MILK], { token: '7:3' }));
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => ({ list: useFridge(1), save: useUpdateFridge() }), { wrapper });
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));

    const refocus = () => act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    const markStale = () =>
      queryClient.setQueryData(['fridge', 1], queryClient.getQueryData(['fridge', 1]), { updatedAt: 1 });

    const put = deferred<ReturnType<typeof reply>>();
    mockedAuthFetch.mockReturnValueOnce(put.promise);
    result.current.save.mutate({ userId: 1, items: [MILK, EGGS] });
    await waitFor(() => expect(puts()).toHaveLength(1));

    markStale();
    refocus();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(gets()).toHaveLength(1);

    put.resolve(reply([MILK, EGGS], { token: '7:4' }));
    await waitFor(() => expect(result.current.save.isSuccess).toBe(true));

    // The control: with no save pending, the same focus does refetch.
    mockedAuthFetch.mockResolvedValueOnce(reply([MILK, EGGS], { token: '7:4' }));
    markStale();
    refocus();
    await waitFor(() => expect(gets()).toHaveLength(2));
    focusManager.setFocused(undefined);
  });
});

describe('staples version token', () => {
  it('sends the token the caller gives, not the cached one', async () => {
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(['staples', 1], { items: [{ name: 'Salt' }], token: '7:6' });
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'X-Staples-Version': '7:3' }),
      json: () => Promise.resolve([{ name: 'Oil' }]),
    });

    const { result } = renderHook(() => useUpdateStaples(), { wrapper });
    result.current.mutate({ userId: 1, items: [{ name: 'Oil' }], token: '7:2' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/staples', {
      method: 'PUT',
      body: JSON.stringify([{ name: 'Oil' }]),
      headers: { 'X-Staples-Version': '7:2' },
    });
  });
});
