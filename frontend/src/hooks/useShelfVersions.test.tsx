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

const MILK: StockItem = { name: 'Milk', quantity_grams: 500, need_to_use: false };
const EGGS: StockItem = { name: 'Eggs', quantity_grams: 300, need_to_use: false };
const REFUSED = "The fridge was changed on another device, so your change wasn't saved.";

function reply(body: unknown, { status = 200, token }: { status?: number; token?: string } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(token ? { 'X-Fridge-Version': token } : {}),
    json: () => Promise.resolve(body),
  };
}

type Gate = { open: Promise<void>; release: () => void };
function gate(): Gate {
  let release!: () => void;
  const open = new Promise<void>((r) => { release = r; });
  return { open, release };
}

/** Behaves like the real endpoint: a token must equal the current version, and
 *  every accepted write counts up. `gates` holds PUTs back, one each, in order. */
function mockServer(initial: StockItem[], version = 3) {
  const server = {
    items: initial,
    version,
    gates: [] as Gate[],
    failNext: false,
    log: [] as string[],
  };
  mockedAuthFetch.mockImplementation(
    async (_url: string, opts?: { method?: string; body?: string; headers?: Record<string, string> }) => {
      if (opts?.method !== 'PUT') return reply(server.items, { token: `7:${server.version}` });
      await server.gates.shift()?.open;
      if (server.failNext) {
        server.failNext = false;
        return reply({}, { status: 500 });
      }
      const sent = opts.headers?.['X-Fridge-Version'];
      if (sent !== undefined && sent !== `7:${server.version}`) {
        server.log.push(`${sent} refused`);
        return reply({ detail: REFUSED }, { status: 409 });
      }
      server.version += 1;
      server.items = JSON.parse(opts.body ?? '[]') as StockItem[];
      server.log.push(`${sent} accepted`);
      return reply(server.items, { token: `7:${server.version}` });
    },
  );
  return server;
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
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)); });

beforeEach(() => {
  mockedAuthFetch.mockReset();
});

describe('fridge version token', () => {
  it('keeps the token beside the list, and components see only the list', async () => {
    mockServer([MILK]);
    const { queryClient, wrapper } = setup();

    const { result } = renderHook(() => useFridge(1), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([MILK]);
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK], token: '7:3' });
  });

  it('sends the token it is given and caches the one the save got back', async () => {
    mockServer([MILK]);
    const { queryClient, wrapper } = setup();

    const { result } = renderHook(() => useUpdateFridge(), { wrapper });
    result.current.mutate({ userId: 1, items: [MILK, EGGS], token: '7:3' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
      method: 'PUT',
      body: JSON.stringify([MILK, EGGS]),
      headers: { 'X-Fridge-Version': '7:3' },
    });
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK, EGGS], token: '7:4' });
  });

  it('two quick saves by one caller: the second waits and follows the first', async () => {
    const server = mockServer([]);
    const first = gate();
    const second = gate();
    server.gates.push(first, second);
    const { queryClient, wrapper } = setup();

    const { result } = renderHook(() => useUpdateFridge(), { wrapper });
    // Both made from the list at 7:3; the second's list has the first's edit.
    result.current.mutate({ userId: 1, items: [MILK], token: '7:3' });
    result.current.mutate({ userId: 1, items: [MILK, EGGS], token: '7:3' });

    await settle();
    expect(puts()).toHaveLength(1);

    first.release();
    await waitFor(() => expect(puts()).toHaveLength(2));
    // Cached as a matching pair at every step, never a list with a later token.
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK], token: '7:4' });

    second.release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(server.log).toEqual(['7:3 accepted', '7:4 accepted']);
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK, EGGS], token: '7:5' });
  });

  it("a save from another component is not followed: its list lacks that save's edit", async () => {
    // The planner's expired-items save and the Fridge panel share one queue.
    const server = mockServer([MILK, EGGS]);
    const held = gate();
    server.gates.push(held);
    const { wrapper } = setup();

    const { result } = renderHook(() => ({ planner: useUpdateFridge(), panel: useUpdateFridge() }), { wrapper });
    result.current.planner.mutate({ userId: 1, items: [MILK], token: '7:3' });
    result.current.panel.mutate({ userId: 1, items: [MILK, EGGS], token: '7:3' });
    await waitFor(() => expect(puts()).toHaveLength(1));

    held.release();

    await waitFor(() => expect(result.current.panel.isError).toBe(true));
    expect(result.current.panel.error).toBeInstanceOf(ShelfChangedError);
    expect(server.log).toEqual(['7:3 accepted', '7:3 refused']);
    expect(server.items).toEqual([MILK]);
  });

  it('a 409 carries the sentence and reloads; saves made from the old list are refused too, later ones go through', async () => {
    const server = mockServer([MILK]);
    const held = gate();
    server.gates.push(held);
    const { queryClient, wrapper } = setup();

    const { result } = renderHook(() => ({ list: useFridge(1), save: useUpdateFridge() }), { wrapper });
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));

    // A partner writes after this phone loaded the list at 7:3.
    server.items = [EGGS];
    server.version = 8;
    result.current.save.mutate({ userId: 1, items: [MILK, EGGS], token: '7:3' });
    result.current.save.mutate({ userId: 1, items: [], token: '7:3' });
    await waitFor(() => expect(puts()).toHaveLength(1));
    held.release();

    await waitFor(() => expect(puts()).toHaveLength(2));
    await waitFor(() => expect(result.current.save.isError).toBe(true));
    expect(result.current.save.error).toBeInstanceOf(ShelfChangedError);
    expect(result.current.save.error?.message).toBe(REFUSED);
    expect(server.log).toEqual(['7:3 refused', '7:3 refused']);
    expect(server.items).toEqual([EGGS]);
    await waitFor(() =>
      expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [EGGS], token: '7:8' }),
    );

    result.current.save.mutate({ userId: 1, items: [EGGS, MILK], token: '7:8' });
    await waitFor(() => expect(result.current.save.isSuccess).toBe(true));
    expect(server.log).toEqual(['7:3 refused', '7:3 refused', '7:8 accepted']);
  });

  it('a save that fails leaves the cached list and token a matching pair', async () => {
    const server = mockServer([]);
    const first = gate();
    const second = gate();
    server.gates.push(first, second);
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(['fridge', 1], { items: [], token: '7:3' });

    const { result } = renderHook(() => useUpdateFridge(), { wrapper });
    result.current.mutate({ userId: 1, items: [MILK], token: '7:3' });
    result.current.mutate({ userId: 1, items: [MILK, EGGS], token: '7:3' });
    await waitFor(() => expect(puts()).toHaveLength(1));

    first.release();
    await waitFor(() => expect(puts()).toHaveLength(2));
    server.failNext = true;
    second.release();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).not.toBeInstanceOf(ShelfChangedError);
    // What the server holds, so a list later made from the cache loses nothing.
    expect(server.items).toEqual([MILK]);
    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK], token: '7:4' });
  });

  it('a GET in flight when a save lands is dropped, so it cannot roll the save back', async () => {
    mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => ({ list: useFridge(1), save: useUpdateFridge() }), { wrapper });
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));

    const served = mockedAuthFetch.getMockImplementation() as (u: string, o?: unknown) => Promise<unknown>;
    let answerGet!: (value: unknown) => void;
    mockedAuthFetch.mockImplementationOnce(() => new Promise((r) => { answerGet = r; }));
    mockedAuthFetch.mockImplementation(served);
    act(() => { void queryClient.invalidateQueries({ queryKey: ['fridge'] }); });
    await waitFor(() => expect(gets()).toHaveLength(2));

    result.current.save.mutate({ userId: 1, items: [MILK, EGGS], token: '7:3' });
    await waitFor(() => expect(result.current.save.isSuccess).toBe(true));
    // The GET was served before the save and answers after it.
    answerGet(reply([MILK], { token: '7:3' }));
    await settle();

    expect(queryClient.getQueryData(['fridge', 1])).toEqual({ items: [MILK, EGGS], token: '7:4' });
  });

  it('no token known: the PUT carries no header at all', async () => {
    mockServer([MILK]);
    const { wrapper } = setup();

    const { result } = renderHook(() => useUpdateFridge(), { wrapper });
    result.current.mutate({ userId: 1, items: [MILK], token: null });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
      method: 'PUT',
      body: JSON.stringify([MILK]),
    });
  });

  it('refetches when the window regains focus once the list is stale, not before', async () => {
    mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useFridge(1), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const refocus = () => act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });

    refocus();
    await settle();
    expect(gets()).toHaveLength(1);

    queryClient.setQueryData(['fridge', 1], queryClient.getQueryData(['fridge', 1]), { updatedAt: 1 });
    refocus();
    await waitFor(() => expect(gets()).toHaveLength(2));
    focusManager.setFocused(undefined);
  });
});

describe('staples version token', () => {
  it('sends its own header', async () => {
    const { wrapper } = setup();
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
