import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as AuthCtx from '../contexts/AuthContext';
import { RestockDialog } from './RestockDialog';
import { useFridge } from '../hooks/useServerState';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import type { AuthState, Household, MealPlanSummary, PlanStatus, StockItem } from '../types';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchHousehold: vi.fn(),
  scanReceipt: vi.fn(),
  mergeFridgeItems: vi.fn(),
  recordWaste: vi.fn(),
}));

import { authFetch, fetchHousehold, mergeFridgeItems, recordWaste, scanReceipt } from '../api';

const mockedAuthFetch = vi.mocked(authFetch);
const mockedScan = vi.mocked(scanReceipt);

type Row = Omit<StockItem, 'id'>;
type Call = [string, { method?: string; body?: string; headers?: Record<string, string> }?];
const MILK: Row = { name: 'Milk', quantity_grams: 500, need_to_use: false };
const APPLE: Row = { name: 'Apple', quantity_grams: 300, need_to_use: false };
const REFUSED = "The fridge was changed on another device, so your change wasn't saved.";

const reply = (body: unknown, status = 200, token?: string) =>
  ({
    ok: status < 400,
    status,
    headers: new Headers(token ? { 'X-Fridge-Version': token } : {}),
    json: () => Promise.resolve(body),
  }) as Response;

function plan(id: number, status: PlanStatus): MealPlanSummary {
  return {
    id, status, created_at: '2026-10-20T10:00:00Z', days: 3, meals_per_day: 2, people_count: 2,
    start_date: null, total_meals: 6, cooked_meals: 0, finished_at: null,
  };
}

/** The real endpoint's contract: a PUT must carry the current version, every
 *  write renumbers the rows, and a finish that restores food is a write. */
function mockServer(initial: Row[], plans: MealPlanSummary[] = [], sendToken = true) {
  let nextId = 100;
  const renumber = (rows: Row[]): StockItem[] => rows.map((r) => ({ ...r, id: nextId++ }));
  const server = {
    items: renumber(initial),
    version: 3,
    plans,
    holdGet: null as Promise<void> | null,
    holdPut: null as Promise<void> | null,
    holdFinish: null as Promise<void> | null,
    /** Commit the next PUT, then lose its reply (a dropped connection). */
    dropReply: false,
    failPut: false,
    /** The next GET /fridge fails (500), or comes back without a version token. */
    failGet: false,
    noTokenOnGet: false,
    write(rows: Row[]) {
      server.items = renumber(rows);
      server.version += 1;
    },
  };
  const token = () => (sendToken ? `1:${server.version}` : undefined);
  mockedAuthFetch.mockImplementation((async (url: string, opts?: Call[1]) => {
    if (url === '/plan') return reply(server.plans);
    const finish = url.match(/^\/plan\/(\d+)\/finish$/);
    if (finish) {
      if (server.holdFinish) await server.holdFinish;
      server.plans = server.plans.filter((p) => p.id !== Number(finish[1]));
      server.write([...server.items, APPLE]);
      return reply({});
    }
    if (url.startsWith('/fridge') && opts?.method === 'PUT') {
      if (server.holdPut) await server.holdPut;
      if (server.failPut) return reply({}, 500);
      if (opts.headers?.['X-Fridge-Version'] !== `1:${server.version}`) {
        return reply({ detail: REFUSED }, 409);
      }
      server.write(JSON.parse(opts.body ?? '[]') as Row[]);
      if (server.dropReply) {
        server.dropReply = false;
        throw new TypeError('Failed to fetch');
      }
      return reply(server.items, 200, token());
    }
    if (url === '/fridge') {
      if (server.holdGet) await server.holdGet;
      if (server.failGet) return reply({}, 500);
      return reply(server.items, 200, server.noTokenOnGet ? undefined : token());
    }
    throw new Error(`unexpected ${url}`);
  }) as typeof authFetch);
  return server;
}

function setAuth(over: Partial<AuthState> = {}) {
  vi.spyOn(AuthCtx, 'useAuth').mockReturnValue({
    userId: 1, isDemo: false, householdsEnabled: true, ...over,
  } as unknown as AuthState);
}

function household(members: number): Household {
  return {
    members: Array.from({ length: members }, (_, i) => ({
      id: i + 1, email: `m${i}@example.com`, profile: null, needs_consent: false,
    })),
    invites: [], max_members: 6, max_live_invites: 3,
  };
}

/** Like every entry point: the dialog renders only once the fridge GET landed. */
function renderDialog() {
  const onClose = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Harness() {
    const { data } = useFridge(1);
    return data ? <RestockDialog onClose={onClose} /> : null;
  }
  const view = render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
  return { ...view, onClose, queryClient };
}

/** A request held until the test opens it. */
function gate() {
  let open = () => {};
  const promise = new Promise<void>((r) => { open = () => r(); });
  return { promise, open: () => act(async () => open()) };
}

const puts = () =>
  (mockedAuthFetch.mock.calls as unknown as Call[]).filter((c) => c[1]?.method === 'PUT');

let nextScan = 7;
function scanReturns(...names: string[]) {
  mockedScan.mockResolvedValueOnce({
    generation_id: nextScan++,
    items: names.map((name) => ({
      name, quantity_grams: 200, need_to_use: false, item_type: 'ingredient' as const,
      expiration_date: '2030-01-01',
    })),
  });
}

async function scan(user: ReturnType<typeof userEvent.setup>, ...names: string[]) {
  scanReturns(...names);
  await user.upload(
    await screen.findByLabelText(/select receipt image|vyberte obrázek/i),
    new File(['x'], 'r.jpg', { type: 'image/jpeg' }),
  );
  for (const name of names) expect(await screen.findByDisplayValue(name)).toBeInTheDocument();
}

const saveButton = () => screen.getByRole('button', { name: /^replace the fridge with/i });

beforeEach(() => {
  nextScan = 7;
  mockedAuthFetch.mockReset();
  mockedScan.mockReset();
  vi.mocked(fetchHousehold).mockResolvedValue(household(1));
  setAuth();
});

afterEach(() => {
  // Unmount first: a re-render after the useAuth spy is gone would throw.
  cleanup();
  vi.restoreAllMocks();
  useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
});

describe('RestockDialog', () => {
  it('replaces the fridge with one PUT: the token from mount, one id per scan, no waste', async () => {
    mockServer([MILK]);
    const user = userEvent.setup();
    renderDialog();
    expect(
      await screen.findByText('Saving replaces your fridge list (1 item) with what you scan now.'),
    ).toBeInTheDocument();

    await scan(user, 'Eggs');
    await scan(user, 'Butter');
    await user.click(screen.getByRole('button', { name: 'Replace the fridge with these 2 items' }));

    expect(await screen.findByText('Your fridge now has 2 items')).toBeInTheDocument();
    expect(puts()).toHaveLength(1);
    const [url, opts] = puts()[0];
    expect(url).toBe('/fridge?generation_id=7&generation_id=8');
    expect(opts?.headers).toEqual({ 'X-Fridge-Version': '1:3' });
    expect(JSON.parse(opts?.body ?? '').map((r: Row) => r.name)).toEqual(['Eggs', 'Butter']);
    expect(mergeFridgeItems).not.toHaveBeenCalled();
    expect(recordWaste).not.toHaveBeenCalled();
    expect(mockedAuthFetch.mock.calls.some((c) => String(c[0]).includes('/waste'))).toBe(false);
  });

  it('after a 409 the rows stay, and the next save waits for the reload and carries its token', async () => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    renderDialog();
    await scan(user, 'Eggs');
    // A partner's edit while the dialog was open, and a plan they confirmed.
    server.write([APPLE]);
    server.plans = [plan(9, 'planned')];
    const reload = gate();
    server.holdGet = reload.promise;

    await user.click(saveButton());
    await waitFor(() => expect(puts()).toHaveLength(1));
    // The reload is still out: Save must not go again with the refused token.
    await act(() => new Promise((r) => setTimeout(r, 20)));
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();

    server.holdGet = null;
    await reload.open();
    expect(
      await screen.findByText(
        'Someone changed the fridge list while you were scanning. Saving now replaces their change too.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(REFUSED)).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('Eggs')).toBeInTheDocument();
    // The plan list was read again too.
    expect(screen.getByRole('button', { name: 'Finish it' })).toBeInTheDocument();
    await waitFor(() => expect(saveButton()).toBeEnabled());

    await user.click(saveButton());
    expect(await screen.findByText('Your fridge now has 1 item')).toBeInTheDocument();
    expect(puts()[1][1]?.headers).toEqual({ 'X-Fridge-Version': '1:4' });
  });

  it.each([
    ['fails', 'failGet'],
    ['comes back without a token', 'noTokenOnGet'],
  ] as const)('a reload that %s after a 409 says saving failed, keeps the rows, and the next try recovers', async (_, flag) => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    renderDialog();
    await scan(user, 'Eggs');
    server.write([APPLE]); // a partner's edit: the save gets a 409
    server[flag] = true;

    await user.click(saveButton());
    expect(
      await screen.findByText('Saving failed. Your scanned items are still here, so you can try again.'),
    ).toBeInTheDocument();
    // Not blamed on someone else, and the paid rows are still on screen.
    expect(screen.queryByText(/someone changed the fridge list/i)).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('Eggs')).toBeInTheDocument();

    // The reload works again: the retry 409s on the old token, reloads, and
    // the third save goes through with the fresh one.
    server[flag] = false;
    await waitFor(() => expect(saveButton()).toBeEnabled());
    await user.click(saveButton());
    await screen.findByText(/someone changed the fridge list/i);
    await waitFor(() => expect(saveButton()).toBeEnabled());
    await user.click(saveButton());
    expect(await screen.findByText('Your fridge now has 1 item')).toBeInTheDocument();
  });

  it('sends the token from mount even when the cached list refreshed under the dialog', async () => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    const { queryClient } = renderDialog();
    await scan(user, 'Eggs');
    // A focus refetch brings a partner's write into the cache; the dialog did
    // not re-read, so its save must still name the list it showed (and fail).
    server.write([APPLE]);
    await act(() => queryClient.refetchQueries({ queryKey: ['fridge', 1] }));
    expect(queryClient.getQueryData<{ token: string }>(['fridge', 1])?.token).toBe('1:4');

    await user.click(saveButton());
    expect(await screen.findByText(/someone changed the fridge list/i)).toBeInTheDocument();
    expect(puts()[0][1]?.headers).toEqual({ 'X-Fridge-Version': '1:3' });
    expect(server.items.map((r) => r.name)).toEqual(['Apple']);
  });

  it('a save whose reply was lost: the retry finds it landed, shows Done, and Undo restores the list it replaced', async () => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    renderDialog();
    await scan(user, 'Eggs');
    server.dropReply = true; // commits, then the connection drops

    await user.click(saveButton());
    expect(
      await screen.findByText('Saving failed. Your scanned items are still here, so you can try again.'),
    ).toBeInTheDocument();
    expect(server.items.map((r) => r.name)).toEqual(['Eggs']);

    // The retry is refused (its token is stale), but the server already holds
    // exactly this list: Done, with no "someone changed it" blame.
    await user.click(saveButton());
    await screen.findByText('Your fridge now has 1 item');
    expect(screen.queryByText(/someone changed the fridge list/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Undo' }));

    // Back to what was there before the restock, not to its own scans.
    await waitFor(() => expect(server.items.map((r) => r.name)).toEqual(['Milk']));
    expect(JSON.parse(puts()[2][1]?.body ?? '')).toEqual([MILK]);
  });

  it('while a save or Undo is out, Close, Finish it and Undo wait, and Confirm says so', async () => {
    const server = mockServer([MILK], [plan(5, 'active')]);
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await scan(user, 'Eggs');
    const put = gate();
    server.holdPut = put.promise;

    await user.click(saveButton());
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Finish it' })).toBeDisabled();
    server.holdPut = null;
    await put.open();
    await screen.findByText('Your fridge now has 1 item');

    const undoPut = gate();
    server.holdPut = undoPut.promise;
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    server.holdPut = null;
    await undoPut.open();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it('while Finish it is out, Empty, the pickers, Confirm and Close wait', async () => {
    const server = mockServer([MILK], [plan(5, 'active'), plan(6, 'planned')]);
    const user = userEvent.setup();
    renderDialog();
    const first = gate();
    server.holdFinish = first.promise;
    await user.click((await screen.findAllByRole('button', { name: 'Finish it' }))[0]);
    expect(screen.getByRole('button', { name: 'Empty the fridge' })).toBeDisabled();
    expect(screen.getByLabelText(/select receipt image/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    for (const b of screen.getAllByRole('button', { name: 'Finish it' })) expect(b).toBeDisabled();
    server.holdFinish = null;
    await first.open();
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Finish it' })).toHaveLength(1));

    await scan(user, 'Eggs');
    const second = gate();
    server.holdFinish = second.promise;
    await user.click(screen.getByRole('button', { name: 'Finish it' }));
    expect(saveButton()).toBeDisabled();
    server.holdFinish = null;
    await second.open();
    await waitFor(() => expect(saveButton()).toBeEnabled());
    expect(puts()).toHaveLength(0);
  });

  it('a refused Empty the fridge shows its sentence as an alert', async () => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    renderDialog();
    await screen.findByRole('button', { name: 'Empty the fridge' });
    server.write([APPLE]);
    await user.click(screen.getByRole('button', { name: 'Empty the fridge' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/someone changed the fridge list/i);
  });

  it('says the fridge is shared only when the household has more than one member', async () => {
    mockServer([MILK]);
    const shared = 'You share this fridge. The new list replaces it for everyone in your household.';
    const first = renderDialog();
    await screen.findByText(/saving replaces your fridge list/i);
    await waitFor(() => expect(fetchHousehold).toHaveBeenCalled());
    expect(screen.queryByText(shared)).not.toBeInTheDocument();
    first.unmount();

    vi.mocked(fetchHousehold).mockResolvedValue(household(2));
    renderDialog();
    expect(await screen.findByText(shared)).toBeInTheDocument();
  });

  it('names only planned and active plans, never cooked or finished ones', async () => {
    mockServer([MILK], [plan(1, 'planned'), plan(2, 'active'), plan(3, 'cooked'), plan(4, 'finished')]);
    renderDialog();
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Finish it' })).toHaveLength(2));
    expect(screen.getAllByText(/is not finished\. Finish it first/)).toHaveLength(2);
  });

  it('Finish it, then reads the fridge and the plans again: the next save carries the new token', async () => {
    mockServer([MILK], [plan(5, 'active')]);
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('button', { name: 'Finish it' }));

    await waitFor(() => expect(screen.queryByRole('button', { name: 'Finish it' })).not.toBeInTheDocument());
    // The finish put food back: the header counts the list as it is now.
    expect(
      await screen.findByText('Saving replaces your fridge list (2 items) with what you scan now.'),
    ).toBeInTheDocument();
    await scan(user, 'Eggs');
    await user.click(saveButton());
    expect(await screen.findByText('Your fridge now has 1 item')).toBeInTheDocument();
    expect(puts()[0][1]?.headers).toEqual({ 'X-Fridge-Version': '1:4' });
  });

  it('shows a translated error when Finish it fails, and still reads the plans again', async () => {
    const server = mockServer([MILK], [plan(5, 'active')]);
    const answer = mockedAuthFetch.getMockImplementation();
    mockedAuthFetch.mockImplementation((async (url: string, opts?: Call[1]) =>
      url.endsWith('/finish') ? reply({}, 500) : answer?.(url, opts)) as typeof authFetch);
    const user = userEvent.setup();
    renderDialog();
    await screen.findByRole('button', { name: 'Finish it' });
    server.plans = []; // a partner finished it from their phone meanwhile
    await user.click(screen.getByRole('button', { name: 'Finish it' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't finish the plan. Try again.");
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Finish it' })).not.toBeInTheDocument());
    expect(server.version).toBe(3);
  });

  it('Empty the fridge saves an empty list through the same checked PUT', async () => {
    mockServer([MILK, APPLE]);
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('button', { name: 'Empty the fridge' }));

    expect(await screen.findByText('Your fridge now has 0 items')).toBeInTheDocument();
    expect(puts()).toHaveLength(1);
    expect(puts()[0][0]).toBe('/fridge');
    expect(puts()[0][1]?.body).toBe('[]');
    expect(puts()[0][1]?.headers).toEqual({ 'X-Fridge-Version': '1:3' });
    expect(recordWaste).not.toHaveBeenCalled();
  });

  it('Undo puts the old list back without ids, with the token the save returned', async () => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await scan(user, 'Eggs');
    await user.click(saveButton());
    await user.click(await screen.findByRole('button', { name: 'Undo' }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    const [, opts] = puts()[1];
    expect(opts?.headers).toEqual({ 'X-Fridge-Version': '1:4' });
    expect(JSON.parse(opts?.body ?? '')).toEqual([MILK]); // no `id` key at all
    expect(server.items.map((r) => r.name)).toEqual(['Milk']);
  });

  it('Undo is refused once anyone wrote since the save', async () => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await scan(user, 'Eggs');
    await user.click(saveButton());
    await screen.findByRole('button', { name: 'Undo' });
    server.write([APPLE]);

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "The fridge changed after your save, so it can't be undone.",
    );
    // Neither the count nor an Undo that can never work stays on screen.
    expect(screen.queryByText('Your fridge now has 1 item')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close' })).toBeEnabled();
    expect(onClose).not.toHaveBeenCalled();
    expect(server.items.map((r) => r.name)).toEqual(['Apple']);
  });

  it('an Undo that failed for another reason says so in words and can be tried again', async () => {
    const server = mockServer([MILK]);
    const user = userEvent.setup();
    renderDialog();
    await scan(user, 'Eggs');
    await user.click(saveButton());
    await screen.findByRole('button', { name: 'Undo' });
    server.failPut = true;

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/^Undo failed\. Try again\.$/);
    expect(screen.getByText('Your fridge now has 1 item')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled();
  });

  it('without a token it offers no scanner and never sends a PUT', async () => {
    mockServer([MILK], [], false);
    renderDialog();
    expect(await screen.findByText('Loading inventory...')).toBeInTheDocument();
    expect(screen.queryByLabelText(/select receipt image/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Empty the fridge' })).not.toBeInTheDocument();
    expect(puts()).toHaveLength(0);
  });

  it('Escape and the backdrop do not close it; Close does, and has the focus on open', async () => {
    mockServer([MILK]);
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    const dialog = await screen.findByRole('dialog');
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('leaves no untranslated English in Czech: header, plan notice, review and Done', async () => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    vi.mocked(fetchHousehold).mockResolvedValue(household(2));
    mockServer([MILK], [plan(5, 'active')]);
    const user = userEvent.setup();
    const { container } = renderDialog();
    await screen.findByText('Lednici sdílíte. Nový seznam uvidí místo starého všichni v domácnosti.');
    await screen.findByRole('button', { name: 'Dokončit' });
    expect(untranslatedEnglishIn(container)).toEqual([]);

    await scan(user, 'Vejce');
    expect(untranslatedEnglishIn(container)).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'Nahradit lednici touto 1 položkou' }));
    await screen.findByText('V lednici je teď 1 položka');
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });
});
