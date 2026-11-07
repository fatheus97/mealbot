import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { stubLocationReload } from '../test/location';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Fridge } from './Fridge';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import { AuthProvider } from '../contexts/AuthContext';
import { setMobileViewport } from '../test/test-utils';
import type { ReactNode } from 'react';
import type { StockItem } from '../types';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
  recordWaste: vi.fn(),
}));

import { authFetch, fetchUserProfile, recordWaste } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedFetchProfile = fetchUserProfile as ReturnType<typeof vi.fn>;
const mockedRecordWaste = recordWaste as ReturnType<typeof vi.fn>;

/** A profile payload with everything the Fridge reads off it. */
function profileFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    email: 'test@test.com',
    country: null,
    language: 'English',
    measurement_system: 'metric',
    variability: 'traditional',
    include_spices: true,
    track_snacks: true,
    show_pieces: false,
    need_to_use_enabled: true,
    waste_tracking_enabled: false,
    onboarding_completed: true,
    is_admin: false,
    default_day_layout: null,
    ...overrides,
  };
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

function loginUser() {
  localStorage.setItem('mealbot_token', 'test-token');
  localStorage.setItem('mealbot_user_id', '1');
  localStorage.setItem('mealbot_user_email', 'test@test.com');
}

beforeEach(() => {
  stubLocationReload();
});

describe('Fridge', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it('leaves no untranslated English when switched to Czech (logged out)', () => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    const { container } = render(<Fridge />, { wrapper: createWrapper() });
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });

  it('leaves no untranslated English with items, on desktop AND mobile', async () => {
    // The logged-out case above renders two strings. Everything else — the
    // table headers, the sort chips, the cards, the batch counts, the
    // use-soon badge — needs a populated fridge, and the desktop table and
    // the mobile cards are entirely separate JSX branches.
    for (const mobile of [false, true]) {
      loginUser();
      setMobileViewport(mobile);
      useLocaleStore.setState({ locale: 'cs', explicit: true });
      mockedAuthFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve([
            { name: 'Kuřecí maso', quantity_grams: 500, need_to_use: false },
            // Two batches of the same name exercise the group row + plural.
            { name: 'Rýže', quantity_grams: 1000, need_to_use: true, expiration_date: '2026-09-01' },
            { name: 'Rýže', quantity_grams: 400, need_to_use: false, expiration_date: '2026-10-01' },
          ]),
      });

      const { container, unmount } = render(<Fridge />, { wrapper: createWrapper() });
      await waitFor(() => expect(screen.getByText('Kuřecí maso')).toBeInTheDocument());
      expect(untranslatedEnglishIn(container)).toEqual([]);

      // Expand the two-batch group. `expandedGroups` starts empty, so the
      // per-batch sub-rows never mount otherwise — and that is where "Batch 1"
      // sat untranslated through a full review of this slice.
      await userEvent.click(screen.getByText('Rýže'));
      await waitFor(() => expect(screen.getByText(/Balení 1/)).toBeInTheDocument());
      expect(untranslatedEnglishIn(container)).toEqual([]);

      unmount();
      localStorage.clear();
    }
  });

  it('shows "Please log in" when no userId', () => {
    render(<Fridge />, { wrapper: createWrapper() });
    expect(screen.getByText(/please log in/i)).toBeInTheDocument();
    // Nothing to explain about a fridge the visitor cannot see.
    expect(screen.queryByRole('button', { name: 'How the fridge changes' })).not.toBeInTheDocument();
  });

  it('explains what changes the fridge, and opening the hint does not collapse it', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Chicken', quantity_grams: 500, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Chicken')).toBeInTheDocument());

    // The hint sits inside the clickable collapse header; InfoHint stops its
    // click, so the section must stay open.
    await user.click(screen.getByRole('button', { name: 'How the fridge changes' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent(/soonest date first/i);
    expect(screen.getByText('Chicken')).toBeInTheDocument();
  });

  it('renders items as cards (not a table) on a mobile viewport', async () => {
    loginUser();
    setMobileViewport(true);
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve([
          { name: 'Chicken', quantity_grams: 500, need_to_use: false },
          { name: 'Rice', quantity_grams: 1000, need_to_use: true },
        ]),
    });

    render(<Fridge />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Chicken')).toBeInTheDocument());

    // Mobile branch: the 5-col table is replaced by cards + sort chips.
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Name/ })).toBeInTheDocument();
    // Each item is a card with its own Edit/Remove (still wired to the same handlers).
    expect(screen.getAllByRole('button', { name: /^Edit$/ })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /^Remove$/ })).toHaveLength(2);
    // need_to_use item surfaces the "use soon" badge.
    expect(screen.getByText(/use soon/i)).toBeInTheDocument();
  });

  it('renders server items as read-only text', async () => {
    loginUser();
    const items = [
      { name: 'Chicken', quantity_grams: 500, need_to_use: false },
      { name: 'Rice', quantity_grams: 1000, need_to_use: true },
    ];

    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(items),
    });

    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Chicken')).toBeInTheDocument();
    });

    expect(screen.getByText('Rice')).toBeInTheDocument();
  });

  it('hides the need-to-use column when the preference is disabled', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce({
      id: 1,
      email: 'test@test.com',
      country: null,
      language: 'English',
      measurement_system: 'metric',
      variability: 'traditional',
      include_spices: true,
      track_snacks: true,
      show_pieces: false,
      need_to_use_enabled: false,
      onboarding_completed: true,
      is_admin: false,
      default_day_layout: null,
    });
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      // The backend already masks need_to_use to false at the source when the
      // preference is off — this data models that server contract.
      json: () => Promise.resolve([{ name: 'Chicken', quantity_grams: 500, need_to_use: false }]),
    });

    render(<Fridge />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Chicken')).toBeInTheDocument());

    expect(screen.queryByText('Need to use?')).not.toBeInTheDocument();
  });

  it('hides the mobile "use soon" badge when the preference is disabled, even if the item data says true', async () => {
    // Regression: the backend masks need_to_use at the source, but the fridge
    // query cache isn't always fresh relative to the preference (staleTime +
    // no refetchOnWindowFocus — see useUpdateUserProfile's invalidation fix).
    // The mobile badges must not depend solely on the server having masked
    // the payload; gate on the preference client-side too. This item's
    // need_to_use is deliberately true to model exactly that stale-cache case.
    loginUser();
    setMobileViewport(true);
    mockedFetchProfile.mockResolvedValueOnce({
      id: 1,
      email: 'test@test.com',
      country: null,
      language: 'English',
      measurement_system: 'metric',
      variability: 'traditional',
      include_spices: true,
      track_snacks: true,
      show_pieces: false,
      need_to_use_enabled: false,
      onboarding_completed: true,
      is_admin: false,
      default_day_layout: null,
    });
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Chicken', quantity_grams: 500, need_to_use: true }]),
    });

    render(<Fridge />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Chicken')).toBeInTheDocument());

    expect(screen.queryByText(/use soon/i)).not.toBeInTheDocument();
  });

  it('shows the need-to-use column by default (profile not yet resolved)', async () => {
    loginUser();
    // fetchUserProfile intentionally left unmocked (resolves undefined) —
    // the column must not flicker away while the profile is still loading.
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Chicken', quantity_grams: 500, need_to_use: false }]),
    });

    render(<Fridge />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Chicken')).toBeInTheDocument());

    expect(screen.getByText('Need to use?')).toBeInTheDocument();
  });

  it('adds a new item via modal and auto-saves', async () => {
    loginUser();
    // Load empty fridge
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });
    // Response for auto-save PUT
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Butter', quantity_grams: 100, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/fridge is empty/i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /add ingredient/i }));
    expect(screen.getByText('Add Ingredient')).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/chicken breast/i), 'Butter');
    await user.click(screen.getByRole('button', { name: /ok/i }));

    expect(screen.getByText('Butter')).toBeInTheDocument();

    // Verify auto-save PUT was called
    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
        method: 'PUT',
        body: JSON.stringify([{ name: 'Butter', quantity_grams: 100, need_to_use: false, expiration_date: null }]),
      });
    });
  });

  it('removes an item via confirm dialog and auto-saves', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Milk', quantity_grams: 500, need_to_use: false }]),
    });
    // Response for auto-save PUT (empty fridge after removal)
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Milk')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Remove' }));

    // Confirm dialog appears with item context, fridge state unchanged.
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/Remove "Milk"/)).toBeInTheDocument();
    expect(screen.getByText('Milk')).toBeInTheDocument();

    // Confirm removal — dialog has its own "Remove" button.
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    expect(screen.queryByText('Milk')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Verify auto-save PUT was called with empty array
    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
        method: 'PUT',
        body: JSON.stringify([]),
      });
    });
  });

  it('cancels remove without mutating state', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Milk', quantity_grams: 500, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Milk')).toBeInTheDocument();
    });

    // Snapshot call count before cancel so we can assert no NEW fetches —
    // mockedAuthFetch isn't reset between tests in this file.
    const callsBefore = mockedAuthFetch.mock.calls.length;

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Milk')).toBeInTheDocument();
    // Cancel must not trigger any further fetches (no auto-save PUT).
    expect(mockedAuthFetch.mock.calls.length).toBe(callsBefore);
  });

  it('shows error notice on auto-save failure after confirmed remove', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Eggs', quantity_grams: 200, need_to_use: false }]),
    });

    // Auto-save PUT fails
    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Eggs')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      expect(screen.getByText(/failed to save/i)).toBeInTheDocument();
    });
  });

  it('edits an existing item via modal and auto-saves', async () => {
    loginUser();
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Milk', quantity_grams: 500, need_to_use: false }]),
    });
    // Response for auto-save PUT
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ name: 'Cream', quantity_grams: 500, need_to_use: false }]),
    });

    const user = userEvent.setup();
    render(<Fridge />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Milk')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /edit/i }));

    expect(screen.getByText('Edit Ingredient')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Milk')).toBeInTheDocument();

    const nameInput = screen.getByDisplayValue('Milk');
    await user.clear(nameInput);
    await user.type(nameInput, 'Cream');
    await user.click(screen.getByRole('button', { name: /ok/i }));

    expect(screen.getByText('Cream')).toBeInTheDocument();
    expect(screen.queryByText('Milk')).not.toBeInTheDocument();

    // Verify auto-save PUT was called
    await waitFor(() => {
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
        method: 'PUT',
        body: JSON.stringify([{ name: 'Cream', quantity_grams: 500, need_to_use: false, expiration_date: null }]),
      });
    });
  });
});

describe('Fridge — food-waste capture', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
    mockedRecordWaste.mockReset();
    mockedRecordWaste.mockResolvedValue({ recorded: 1 });
  });

  /**
   * The dialog's confirm button. Must be scoped to the dialog: the row's own
   * "Remove" is still in the document behind it and matches the same name.
   */
  function confirmButton() {
    return within(screen.getByRole('dialog')).getByRole('button', { name: /^remove$/i });
  }

  /** Mock the profile + one fridge GET, then render and wait for the rows. */
  async function renderFridge(
    items: unknown[],
    profileOverrides: Record<string, unknown> = {},
  ) {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(profileFixture(profileOverrides));
    mockedAuthFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(items),
    });
    render(<Fridge />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Spinach')).toBeInTheDocument());
  }

  it('asks nothing extra when the preference is off', async () => {
    await renderFridge([
      { name: 'Spinach', quantity_grams: 200, need_to_use: false, expiration_date: '2026-08-01' },
    ]);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /^remove$/i }));

    // The removal confirm still appears — only the extra question is absent.
    expect(screen.getByText('Remove ingredient?')).toBeInTheDocument();
    expect(screen.queryByText('Where did it go?')).not.toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /threw it out/i })).not.toBeInTheDocument();
  });

  it('records the chosen answer for the removed batch', async () => {
    await renderFridge(
      [{ name: 'Spinach', quantity_grams: 200, need_to_use: false, expiration_date: '2026-08-01' }],
      { waste_tracking_enabled: true },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /^remove$/i }));

    expect(screen.getByText('Where did it go?')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /threw it out/i }));
    await user.click(confirmButton());

    await waitFor(() =>
      expect(mockedRecordWaste).toHaveBeenCalledWith([
        {
          name: 'Spinach',
          quantity_grams: 200,
          expiration_date: '2026-08-01',
          reason: 'thrown_out',
          source: 'fridge_delete',
        },
      ]),
    );
  });

  it('records "eaten" distinctly from "thrown out"', async () => {
    await renderFridge(
      [{ name: 'Spinach', quantity_grams: 200, need_to_use: false, expiration_date: null }],
      { waste_tracking_enabled: true },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /^remove$/i }));
    await user.click(screen.getByRole('radio', { name: /ate it/i }));
    await user.click(confirmButton());

    await waitFor(() =>
      expect(mockedRecordWaste).toHaveBeenCalledWith([
        expect.objectContaining({ reason: 'eaten', expiration_date: null }),
      ]),
    );
  });

  it('removes without recording when the question is left unanswered', async () => {
    // Answering is optional by design: no default is pre-selected, because
    // "eaten" would undercount waste and "thrown out" would invent it.
    await renderFridge(
      [{ name: 'Spinach', quantity_grams: 200, need_to_use: false, expiration_date: null }],
      { waste_tracking_enabled: true },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /^remove$/i }));
    expect(screen.getByRole('radio', { name: /ate it/i })).not.toBeChecked();
    expect(screen.getByRole('radio', { name: /threw it out/i })).not.toBeChecked();

    await user.click(confirmButton());

    // The removal itself still went through...
    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', expect.objectContaining({ method: 'PUT' })),
    );
    // ...and nothing was recorded.
    expect(mockedRecordWaste).not.toHaveBeenCalled();
  });

  it('records one entry per batch, with each batch’s own quantity and expiry', async () => {
    // Regression guard: confirmRemoval splices the fridge array, so the outgoing
    // rows must be read BEFORE the splice. Reading after it would report
    // whatever shifted into those indices — for a group removal, the wrong
    // items entirely, or none at all.
    await renderFridge(
      [
        { name: 'Spinach', quantity_grams: 200, need_to_use: false, expiration_date: '2026-08-01' },
        { name: 'Spinach', quantity_grams: 350, need_to_use: false, expiration_date: '2026-08-05' },
      ],
      { waste_tracking_enabled: true },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /remove all/i }));
    await user.click(screen.getByRole('radio', { name: /threw it out/i }));
    await user.click(screen.getByRole('button', { name: /^remove$/i }));

    await waitFor(() => expect(mockedRecordWaste).toHaveBeenCalledTimes(1));
    const entries = mockedRecordWaste.mock.calls[0][0];
    expect(entries).toHaveLength(2);
    expect(entries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ quantity_grams: 200, expiration_date: '2026-08-01' }),
        expect.objectContaining({ quantity_grams: 350, expiration_date: '2026-08-05' }),
      ]),
    );
    expect(entries.every((e: { reason: string }) => e.reason === 'thrown_out')).toBe(true);
  });

  it('forgets the previous answer when a different item is removed next', async () => {
    await renderFridge(
      [
        { name: 'Spinach', quantity_grams: 200, need_to_use: false, expiration_date: null },
        { name: 'Yogurt', quantity_grams: 500, need_to_use: false, expiration_date: null },
      ],
      { waste_tracking_enabled: true },
    );
    const user = userEvent.setup();
    const removeButtons = screen.getAllByRole('button', { name: /^remove$/i });
    await user.click(removeButtons[0]);
    await user.click(screen.getByRole('radio', { name: /threw it out/i }));
    // Cancel rather than confirm — the answer must not survive the dialog.
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    await user.click(screen.getAllByRole('button', { name: /^remove$/i })[0]);
    expect(screen.getByRole('radio', { name: /threw it out/i })).not.toBeChecked();
    expect(screen.getByRole('radio', { name: /ate it/i })).not.toBeChecked();
  });

  it('leaves no untranslated English in the waste prompt when switched to Czech', async () => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    await renderFridge(
      [{ name: 'Spinach', quantity_grams: 200, need_to_use: false, expiration_date: null }],
      { waste_tracking_enabled: true },
    );
    const user = userEvent.setup();
    await user.click(screen.getAllByRole('button', { name: /odebrat/i })[0]);

    const dialog = screen.getByRole('dialog');
    expect(untranslatedEnglishIn(dialog)).toEqual([]);
  });
});

// Household PR 4b: the list can reload under an open dialog (a focus refetch
// shows a partner's edit), and a save made from an old list is refused (409).
describe('Fridge — changed on another device', () => {
  const REFUSED = "The fridge was changed on another device, so your change wasn't saved.";

  type Row = Omit<StockItem, 'id'>;
  const MILK: Row = { name: 'Milk', quantity_grams: 500, need_to_use: false };
  const APPLE: Row = { name: 'Apple', quantity_grams: 300, need_to_use: false };

  /** Behaves like the real endpoint: the token must equal the current version,
   *  and EVERY write hands back all-new row ids (replace_fridge_items deletes
   *  and re-inserts), so nothing here can lean on an id surviving a write. */
  function mockServer(initial: Row[]) {
    let nextId = 100;
    const renumber = (rows: Row[]): StockItem[] => rows.map((r) => ({ ...r, id: nextId++ }));
    const server = {
      items: renumber(initial),
      version: 3,
      hold: null as Promise<void> | null,
      failPut: false,
      write(rows: Row[]) {
        server.items = renumber(rows);
        server.version += 1;
      },
    };
    mockedAuthFetch.mockImplementation(
      async (url: string, opts?: { method?: string; body?: string; headers?: Record<string, string> }) => {
        if (url !== '/fridge' || opts?.method !== 'PUT') {
          return {
            ok: true, status: 200,
            headers: new Headers({ 'X-Fridge-Version': `1:${server.version}` }),
            json: () => Promise.resolve(server.items),
          };
        }
        if (server.hold) await server.hold;
        if (server.failPut) {
          return { ok: false, status: 500, headers: new Headers(), json: () => Promise.resolve({}) };
        }
        if (opts.headers?.['X-Fridge-Version'] !== `1:${server.version}`) {
          return {
            ok: false, status: 409, headers: new Headers(),
            json: () => Promise.resolve({ detail: REFUSED }),
          };
        }
        server.write(JSON.parse(opts.body ?? '[]') as Row[]);
        return {
          ok: true, status: 200,
          headers: new Headers({ 'X-Fridge-Version': `1:${server.version}` }),
          json: () => Promise.resolve(server.items),
        };
      },
    );
    return server;
  }

  function setup() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
    return { queryClient, wrapper };
  }

  const puts = () => mockedAuthFetch.mock.calls.filter((c) => c[1]?.method === 'PUT');
  const names = (rows: StockItem[]) => rows.map((r) => r.name);

  async function rename(user: ReturnType<typeof userEvent.setup>, from: string, to: string) {
    const input = screen.getByDisplayValue(from);
    await user.clear(input);
    await user.type(input, to);
    await user.click(screen.getByRole('button', { name: /^ok$/i }));
  }

  /** A partner's write reaches this screen the way a focus refetch brings it. */
  async function reload(queryClient: QueryClient) {
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['fridge'] });
      // The refetch has settled; its render is still a timer away.
      await new Promise((r) => setTimeout(r, 20));
    });
  }

  const addButton = () => screen.getByRole('button', { name: /add ingredient/i });

  async function addItem(user: ReturnType<typeof userEvent.setup>, name: string) {
    await waitFor(() => expect(addButton()).toBeEnabled());
    await user.click(addButton());
    await user.type(screen.getAllByRole('textbox')[0], name);
    await user.click(screen.getByRole('button', { name: /^ok$/i }));
  }

  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
    mockedAuthFetch.mockReset();
    mockedFetchProfile.mockResolvedValue(profileFixture());
    localStorage.clear();
    loginUser();
    setMobileViewport(false);
  });

  afterEach(() => {
    mockedAuthFetch.mockReset();
    mockedFetchProfile.mockReset();
  });

  it("with no dialog open, a reload shows the partner's change and the next save carries its version", async () => {
    const server = mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    server.write([APPLE, MILK]);
    await reload(queryClient);
    await waitFor(() => expect(screen.getByText('Apple')).toBeInTheDocument());

    await user.click(screen.getAllByRole('button', { name: /^edit$/i })[1]);
    await rename(user, 'Milk', 'Cream');

    await waitFor(() => expect(names(server.items)).toEqual(['Apple', 'Cream']));
    expect(puts()[0][1].headers).toEqual({ 'X-Fridge-Version': '1:4' });
  });

  it('an open edit dialog keeps its row through a reload; its save is refused and the latest list shows', async () => {
    const server = mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /^edit$/i }));
    // Apple lands at index 0, where Milk was when the dialog opened.
    server.write([APPLE, MILK]);
    await reload(queryClient);
    expect(screen.queryByText('Apple')).not.toBeInTheDocument();

    await rename(user, 'Milk', 'Cream');

    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    expect(puts()[0][1].headers).toEqual({ 'X-Fridge-Version': '1:3' });
    expect(names(server.items)).toEqual(['Apple', 'Milk']);
    await waitFor(() => expect(screen.getByText('Apple')).toBeInTheDocument());
    expect(screen.getByText('Milk')).toBeInTheDocument();
    expect(screen.queryByText('Cream')).not.toBeInTheDocument();
  });

  it('a remove dialog does the same, and the row it named is the one still on the server', async () => {
    const server = mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    server.write([APPLE, MILK]);
    await reload(queryClient);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));

    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    expect(names(server.items)).toEqual(['Apple', 'Milk']);
    await waitFor(() => expect(screen.getByText('Apple')).toBeInTheDocument());
    expect(screen.getByText('Milk')).toBeInTheDocument();
  });

  it('cancelling the dialog shows what reloaded under it', async () => {
    const server = mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /^edit$/i }));
    server.write([APPLE, MILK]);
    await reload(queryClient);
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => expect(screen.getByText('Apple')).toBeInTheDocument());
    expect(puts()).toHaveLength(0);
  });

  it('an add dialog holds no row: a reload applies, and the new item goes on the latest list', async () => {
    const server = mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /add ingredient/i }));
    server.write([APPLE, MILK]);
    await reload(queryClient);
    await waitFor(() => expect(screen.getByText('Apple')).toBeInTheDocument());

    await user.type(screen.getAllByRole('textbox')[0], 'Pear');
    await user.click(screen.getByRole('button', { name: /^ok$/i }));

    await waitFor(() => expect(names(server.items)).toEqual(['Apple', 'Milk', 'Pear']));
    expect(screen.queryByText(REFUSED)).not.toBeInTheDocument();
  });

  it('one phone: a dialog left open while its earlier save returns still saves, with both edits', async () => {
    // Every write renumbers the rows, so this is the case an id-based dialog
    // breaks: the save's own answer arrives under the second dialog.
    const server = mockServer([APPLE, MILK]);
    let answer!: () => void;
    server.hold = new Promise((r) => { answer = r; });
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    await user.click(screen.getAllByRole('button', { name: /^edit$/i })[1]);
    await rename(user, 'Milk', 'Cream');
    await waitFor(() => expect(puts()).toHaveLength(1));

    await user.click(screen.getAllByRole('button', { name: /^edit$/i })[0]);
    server.hold = null;
    await act(async () => { answer(); await Promise.resolve(); });
    await waitFor(() => expect(names(server.items)).toEqual(['Apple', 'Cream']));

    await rename(user, 'Apple', 'Pear');

    await waitFor(() => expect(names(server.items)).toEqual(['Pear', 'Cream']));
    expect(puts()[1][1].headers).toEqual({ 'X-Fridge-Version': '1:4' });
    expect(screen.queryByText(REFUSED)).not.toBeInTheDocument();
  });

  it('a queued edit stays on screen while the save before it returns', async () => {
    const server = mockServer([APPLE, MILK]);
    let answerFirst!: () => void;
    let answerSecond!: () => void;
    server.hold = new Promise((r) => { answerFirst = r; });
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    await user.click(screen.getAllByRole('button', { name: /^edit$/i })[1]);
    await rename(user, 'Milk', 'Cream');
    await waitFor(() => expect(puts()).toHaveLength(1));
    await user.click(screen.getAllByRole('button', { name: /^edit$/i })[0]);
    await rename(user, 'Apple', 'Pear');

    // The first answers with a list that lacks Pear; the second is still out.
    server.hold = new Promise((r) => { answerSecond = r; });
    await act(async () => { answerFirst(); await Promise.resolve(); });
    await waitFor(() => expect(puts()).toHaveLength(2));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.getByText('Pear')).toBeInTheDocument();
    expect(screen.getByText('Cream')).toBeInTheDocument();

    server.hold = null;
    await act(async () => { answerSecond(); await Promise.resolve(); });
    await waitFor(() => expect(names(server.items)).toEqual(['Pear', 'Cream']));
    expect(screen.queryByText(REFUSED)).not.toBeInTheDocument();
  });

  it('the edit a dialog just saved stays on screen until the server answers, even with a reload held back', async () => {
    const server = mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /^edit$/i }));
    server.write([APPLE, MILK]);
    await reload(queryClient);

    let answer!: () => void;
    server.hold = new Promise((r) => { answer = r; });
    await rename(user, 'Milk', 'Cream');
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(screen.getByText('Cream')).toBeInTheDocument();
    expect(screen.queryByText('Apple')).not.toBeInTheDocument();

    server.hold = null;
    await act(async () => { answer(); await Promise.resolve(); });
    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
  });

  it('a refused removal records no waste; redoing it records one row', async () => {
    mockedFetchProfile.mockResolvedValue(profileFixture({ waste_tracking_enabled: true }));
    mockedRecordWaste.mockReset();
    mockedRecordWaste.mockResolvedValue({ recorded: 1 });
    const server = mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    const removeWithAnswer = async () => {
      await user.click(screen.getByRole('button', { name: 'Remove' }));
      await user.click(await screen.findByRole('radio', { name: /threw it out/i }));
      await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    };

    server.write([MILK]);
    await removeWithAnswer();
    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    await reload(queryClient);
    expect(mockedRecordWaste).not.toHaveBeenCalled();

    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());
    await removeWithAnswer();

    await waitFor(() => expect(mockedRecordWaste).toHaveBeenCalledTimes(1));
    expect(names(server.items)).toEqual([]);
  });

  it('a refused add on an empty fridge leaves no ghost row, so redoing it saves one item', async () => {
    const server = mockServer([]);
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });

    // A counted write that leaves it empty: the reload keeps the same reference.
    server.write([]);
    await addItem(user, 'Pear');
    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText('Pear')).not.toBeInTheDocument());

    await addItem(user, 'Pear');

    await waitFor(() => expect(names(server.items)).toEqual(['Pear']));
  });

  it('a reload that moved only the token on an empty fridge: the next add carries it', async () => {
    const server = mockServer([]);
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(addButton()).toBeEnabled());

    server.write([]);
    await reload(queryClient);
    await addItem(user, 'Pear');

    await waitFor(() => expect(names(server.items)).toEqual(['Pear']));
    expect(puts()[0][1].headers).toEqual({ 'X-Fridge-Version': '1:4' });
    expect(screen.queryByText(REFUSED)).not.toBeInTheDocument();
  });

  it('Add stays off until the list has loaded', async () => {
    mockedAuthFetch.mockImplementation(() => new Promise(() => {}));
    const { wrapper } = setup();
    render(<Fridge />, { wrapper });

    expect(addButton()).toBeDisabled();
  });

  it('Add stays off after the first load failed: a save would replace the whole fridge', async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: false, status: 500, headers: new Headers(), json: () => Promise.resolve({}),
    });
    const { wrapper } = setup();
    render(<Fridge />, { wrapper });

    await waitFor(() => expect(screen.getByText(/fridge fetch failed/i)).toBeInTheDocument());
    expect(addButton()).toBeDisabled();
  });

  it('a failed background refresh shows no error over a good list', async () => {
    mockServer([MILK]);
    const { queryClient, wrapper } = setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    mockedAuthFetch.mockResolvedValue({
      ok: false, status: 500, headers: new Headers(), json: () => Promise.resolve({}),
    });
    await reload(queryClient);

    expect(queryClient.getQueryState(['fridge', 1])?.status).toBe('error');
    expect(screen.queryByText(/fridge fetch failed/i)).not.toBeInTheDocument();
    expect(screen.getByText('Milk')).toBeInTheDocument();
    expect(addButton()).toBeEnabled();
  });

  it('a reload held back by a save that then fails is applied when the save ends', async () => {
    const server = mockServer([MILK]);
    let answer!: () => void;
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    server.hold = new Promise((r) => { answer = r; });
    await user.click(screen.getByRole('button', { name: /^edit$/i }));
    await rename(user, 'Milk', 'Cream');
    await waitFor(() => expect(puts()).toHaveLength(1));
    server.write([APPLE, MILK]);
    await reload(queryClient);
    expect(screen.queryByText('Apple')).not.toBeInTheDocument();

    server.failPut = true;
    server.hold = null;
    await act(async () => { answer(); await Promise.resolve(); });

    await waitFor(() => expect(screen.getByText('Apple')).toBeInTheDocument());
    expect(screen.getByText(/failed to save/i)).toBeInTheDocument();
  });

  it('a Fridge mounted while a save is out still seeds, instead of showing an empty list', async () => {
    const server = mockServer([MILK]);
    let answer!: () => void;
    const { wrapper } = setup();
    const user = userEvent.setup();
    const first = render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    server.hold = new Promise((r) => { answer = r; });
    await user.click(screen.getByRole('button', { name: /^edit$/i }));
    await rename(user, 'Milk', 'Cream');
    await waitFor(() => expect(puts()).toHaveLength(1));
    first.unmount();

    render(<Fridge />, { wrapper });

    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());
    server.hold = null;
    await act(async () => { answer(); await Promise.resolve(); });
  });

  it('a refusal stays on screen past the notice timer, and the next edit clears it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const server = mockServer([MILK]);
      const { wrapper } = setup();
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      render(<Fridge />, { wrapper });
      await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

      server.write([MILK]);
      await user.click(screen.getByRole('button', { name: 'Remove' }));
      await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
      await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(REFUSED));

      await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
      expect(screen.getByRole('alert')).toHaveTextContent(REFUSED);

      await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());
      await user.click(screen.getByRole('button', { name: /^edit$/i }));
      await rename(user, 'Milk', 'Cream');

      await waitFor(() => expect(names(server.items)).toEqual(['Cream']));
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('a refusal can be dismissed', async () => {
    const server = mockServer([MILK]);
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    server.write([MILK]);
    await user.click(screen.getByRole('button', { name: 'Remove' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(REFUSED));

    await user.click(screen.getByRole('button', { name: 'Dismiss' }));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('a save made from a list that went stale unseen shows the server sentence and the reloaded list', async () => {
    const server = mockServer([MILK]);
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<Fridge />, { wrapper });
    await waitFor(() => expect(screen.getByText('Milk')).toBeInTheDocument());

    // The partner adds Apple; this phone still shows the list at 1:3.
    server.write([MILK, APPLE]);
    await user.click(screen.getByRole('button', { name: 'Remove' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));

    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    expect(screen.queryByText(/failed to save/i)).not.toBeInTheDocument();
    expect(puts()[0][1].headers).toEqual({ 'X-Fridge-Version': '1:3' });
    await waitFor(() => expect(screen.getByText('Apple')).toBeInTheDocument());
    expect(screen.getByText('Milk')).toBeInTheDocument();
  });
});
