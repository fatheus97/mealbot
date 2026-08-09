import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Fridge } from './Fridge';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import { AuthProvider } from '../contexts/AuthContext';
import { setMobileViewport } from '../test/test-utils';
import type { ReactNode } from 'react';

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
  vi.stubGlobal(
    'location',
    Object.defineProperties(
      {},
      {
        ...Object.getOwnPropertyDescriptors(window.location),
        reload: { configurable: true, value: vi.fn() },
      },
    ),
  );
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
