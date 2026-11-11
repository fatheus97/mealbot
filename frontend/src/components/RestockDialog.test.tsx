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
      server.plans = server.plans.filter((p) => p.id !== Number(finish[1]));
      server.write([...server.items, APPLE]);
      return reply({});
    }
    if (url.startsWith('/fridge') && opts?.method === 'PUT') {
      if (opts.headers?.['X-Fridge-Version'] !== `1:${server.version}`) {
        return reply({ detail: REFUSED }, 409);
      }
      server.write(JSON.parse(opts.body ?? '[]') as Row[]);
      return reply(server.items, 200, token());
    }
    if (url === '/fridge') {
      if (server.holdGet) await server.holdGet;
      return reply(server.items, 200, token());
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
    server.write([APPLE]); // a partner's edit while the dialog was open
    let release = () => {};
    server.holdGet = new Promise((r) => { release = r; });

    await user.click(saveButton());
    await waitFor(() => expect(puts()).toHaveLength(1));
    // The reload is still out: Save must not go again with the refused token.
    await act(() => new Promise((r) => setTimeout(r, 20)));
    expect(saveButton()).toBeDisabled();

    await act(async () => {
      server.holdGet = null;
      release();
    });
    expect(
      await screen.findByText(`${REFUSED} Saving again replaces their change too.`),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue('Eggs')).toBeInTheDocument();
    await waitFor(() => expect(saveButton()).toBeEnabled());

    await user.click(saveButton());
    expect(await screen.findByText('Your fridge now has 1 item')).toBeInTheDocument();
    expect(puts()[1][1]?.headers).toEqual({ 'X-Fridge-Version': '1:4' });
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

  it('shows a translated error when Finish it fails', async () => {
    const server = mockServer([MILK], [plan(5, 'active')]);
    const answer = mockedAuthFetch.getMockImplementation();
    mockedAuthFetch.mockImplementation((async (url: string, opts?: Call[1]) =>
      url.endsWith('/finish') ? reply({}, 500) : answer?.(url, opts)) as typeof authFetch);
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('button', { name: 'Finish it' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't finish the plan. Try again.");
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
    expect(onClose).not.toHaveBeenCalled();
    expect(server.items.map((r) => r.name)).toEqual(['Apple']);
  });

  it('without a token it offers no scanner and never sends a PUT', async () => {
    mockServer([MILK], [], false);
    renderDialog();
    expect(await screen.findByText('Loading inventory...')).toBeInTheDocument();
    expect(screen.queryByLabelText(/select receipt image/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Empty the fridge' })).not.toBeInTheDocument();
    expect(puts()).toHaveLength(0);
  });

  it('Escape and the backdrop do not close it; Close does', async () => {
    mockServer([MILK]);
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    const dialog = await screen.findByRole('dialog');
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
