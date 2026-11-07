import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PantryStaples } from './PantryStaples';
import { AuthProvider } from '../contexts/AuthContext';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

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

/** Route authFetch: GET /staples returns `initial`; PUT echoes its own body. */
function mockStaples(initial: { name: string }[]) {
  mockedAuthFetch.mockImplementation((url: string, opts?: { method?: string; body?: string }) => {
    if (url === '/staples' && (!opts || opts.method === undefined)) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(initial) });
    }
    if (url === '/staples' && opts?.method === 'PUT') {
      const body = JSON.parse(opts.body ?? '[]');
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
  });
}

function lastPutBody(): { name: string }[] | null {
  const put = [...mockedAuthFetch.mock.calls].reverse().find(
    (c) => c[0] === '/staples' && c[1]?.method === 'PUT',
  );
  return put ? JSON.parse(put[1].body) : null;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe('PantryStaples', () => {
  it('renders the staples list immediately (settings section, no expand step)', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }, { name: 'Olive Oil' }]);

    render(<PantryStaples />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());
    expect(screen.getByText('Olive Oil')).toBeInTheDocument();
    // The heading carries the count.
    expect(
      screen.getByRole('heading', { name: /pantry staples \(2\)/i }),
    ).toBeInTheDocument();
  });

  it('explains how staples match, beside the heading rather than inside it', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }]);
    const user = userEvent.setup();

    render(<PantryStaples />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    // Exact name: a hint inside the <h4> would add its label to the heading's.
    expect(screen.getByRole('heading', { name: 'Pantry staples (1)' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'How staples are matched' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      /matches exactly .* only on shopping lists made after you save/i,
    );
  });

  it('adds a staple and saves the full list', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }]);
    const user = userEvent.setup();

    render(<PantryStaples />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'Flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByText('Flour')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save staples/i }));

    await waitFor(() =>
      expect(lastPutBody()).toEqual([{ name: 'Salt' }, { name: 'Flour' }]),
    );
    // After a successful save the dirty hint is replaced by the saved notice.
    await waitFor(() => expect(screen.getByText('Saved')).toBeInTheDocument());
  });

  it('removes a staple and saves without it', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }, { name: 'Oil' }]);
    const user = userEvent.setup();

    render(<PantryStaples />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Remove Salt' }));
    expect(screen.queryByText('Salt')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save staples/i }));
    await waitFor(() => expect(lastPutBody()).toEqual([{ name: 'Oil' }]));
  });

  it('will not add a case-insensitive duplicate', async () => {
    loginUser();
    mockStaples([{ name: 'Salt' }]);
    const user = userEvent.setup();

    render(<PantryStaples />, { wrapper: createWrapper() });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'salt');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    // Still exactly one salt chip, and Save stays disabled (nothing changed).
    expect(screen.getAllByText(/^salt$/i)).toHaveLength(1);
    expect(screen.getByRole('button', { name: /save staples/i })).toBeDisabled();
  });
});

// Household PR 4b: a reload must not replace unsaved chips, and Save sends the
// version the chips were made from, so the server refuses it (409) rather than
// letting it overwrite a partner's change.
describe('PantryStaples — changed on another device', () => {
  const REFUSED = "The pantry staples were changed on another device, so your change wasn't saved.";
  let server: { items: { name: string }[]; version: number };

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

  /** A server that counts writes and refuses a PUT with a stale token. */
  function mockVersionedServer() {
    mockedAuthFetch.mockImplementation(
      (url: string, opts?: { method?: string; body?: string; headers?: Record<string, string> }) => {
        const reply = (status: number, body: unknown) => Promise.resolve({
          ok: status === 200,
          status,
          headers: new Headers({ 'X-Staples-Version': `1:${server.version}` }),
          json: () => Promise.resolve(body),
        });
        if (url === '/staples' && opts?.method === 'PUT') {
          if (opts.headers?.['X-Staples-Version'] !== `1:${server.version}`) {
            return reply(409, { detail: REFUSED });
          }
          server = { items: JSON.parse(opts.body ?? '[]'), version: server.version + 1 };
          return reply(200, server.items);
        }
        return reply(200, server.items);
      },
    );
  }

  const sentTokens = () =>
    mockedAuthFetch.mock.calls
      .filter((c) => c[1]?.method === 'PUT')
      .map((c) => c[1].headers?.['X-Staples-Version']);

  beforeEach(() => {
    mockedAuthFetch.mockReset();
    loginUser();
    server = { items: [{ name: 'Salt' }], version: 0 };
    mockVersionedServer();
  });

  it('each save sends the version it was made from, the next one the version the last returned', async () => {
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<PantryStaples />, { wrapper });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'Flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.click(screen.getByRole('button', { name: /save staples/i }));
    await waitFor(() => expect(screen.getByText('Saved')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Remove Salt' }));
    await user.click(screen.getByRole('button', { name: /save staples/i }));
    await waitFor(() => expect(server.items).toEqual([{ name: 'Flour' }]));
    expect(sentTokens()).toEqual(['1:0', '1:1']);
  });

  it('keeps unsaved chips through a reload; Save is refused, then shows the reloaded list', async () => {
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<PantryStaples />, { wrapper });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'Flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    // A partner saves Pepper; the reload reaches this screen mid-edit.
    server = { items: [{ name: 'Salt' }, { name: 'Pepper' }], version: 1 };
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['staples'] });
      // The refetch has settled; its render is still a timer away.
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText('Flour')).toBeInTheDocument();
    expect(screen.queryByText('Pepper')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save staples/i }));

    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    expect(sentTokens()).toEqual(['1:0']);
    // The partner's list was not overwritten, and it is what the screen shows.
    expect(server.items).toEqual([{ name: 'Salt' }, { name: 'Pepper' }]);
    expect(screen.getByText('Pepper')).toBeInTheDocument();
    expect(screen.queryByText('Flour')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save staples/i })).toBeDisabled();
  });

  it('a refusal resets the chips even when the partner saved the same names', async () => {
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<PantryStaples />, { wrapper });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'Flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    server = { items: [{ name: 'Salt' }], version: 1 };
    await user.click(screen.getByRole('button', { name: /save staples/i }));

    await waitFor(() => expect(screen.getByText(REFUSED)).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText('Flour')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: /save staples/i })).toBeDisabled();
  });

  it('a save that fails keeps the chips, so it can be saved again', async () => {
    const { wrapper } = setup();
    const user = userEvent.setup();
    const served = mockedAuthFetch.getMockImplementation() as (u: string, o?: { method?: string }) => Promise<unknown>;
    let failing = true;
    mockedAuthFetch.mockImplementation((url: string, opts?: { method?: string }) =>
      opts?.method === 'PUT' && failing
        ? Promise.resolve({ ok: false, status: 500, headers: new Headers(), json: () => Promise.resolve({}) })
        : served(url, opts));
    render(<PantryStaples />, { wrapper });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'Flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.click(screen.getByRole('button', { name: /save staples/i }));

    await waitFor(() => expect(screen.getByText(/update failed/i)).toBeInTheDocument());
    expect(screen.getByText('Flour')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save staples/i })).toBeEnabled();

    failing = false;
    await user.click(screen.getByRole('button', { name: /save staples/i }));

    await waitFor(() => expect(server.items).toEqual([{ name: 'Salt' }, { name: 'Flour' }]));
    expect(sentTokens()).toEqual(['1:0', '1:0']);
  });

  it('no chip can be added until the list has loaded, or Save would replace it', async () => {
    mockedAuthFetch.mockImplementation(() => new Promise(() => {}));
    const { wrapper } = setup();
    const user = userEvent.setup();
    render(<PantryStaples />, { wrapper });

    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
    await user.type(screen.getByLabelText('New staple name'), 'Rice{Enter}');

    expect(screen.queryByText('Rice')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save staples/i })).toBeDisabled();
  });

  it('nor after the first load failed', async () => {
    mockedAuthFetch.mockResolvedValue({
      ok: false, status: 500, headers: new Headers(), json: () => Promise.resolve({}),
    });
    const { wrapper } = setup();
    render(<PantryStaples />, { wrapper });

    await waitFor(() => expect(screen.getByText(/staples fetch failed/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
  });

  it('a failed background refresh shows no error over a good list', async () => {
    const { queryClient, wrapper } = setup();
    render(<PantryStaples />, { wrapper });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    mockedAuthFetch.mockResolvedValue({
      ok: false, status: 500, headers: new Headers(), json: () => Promise.resolve({}),
    });
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['staples'] });
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(queryClient.getQueryState(['staples', 1])?.status).toBe('error');
    expect(screen.queryByText(/staples fetch failed/i)).not.toBeInTheDocument();
    expect(screen.getByText('Salt')).toBeInTheDocument();
  });

  it('a reload that moved only the token: the next save carries it, and is not refused', async () => {
    // A partner saved the same names. The list keeps its reference, so nothing
    // on screen changes, and only the version moved.
    const { queryClient, wrapper } = setup();
    const user = userEvent.setup();
    render(<PantryStaples />, { wrapper });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    server = { items: [{ name: 'Salt' }], version: 1 };
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['staples'] });
      await new Promise((r) => setTimeout(r, 20));
    });

    await user.type(screen.getByLabelText('New staple name'), 'Pepper');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.click(screen.getByRole('button', { name: /save staples/i }));

    await waitFor(() => expect(screen.getByText('Saved')).toBeInTheDocument());
    expect(sentTokens()).toEqual(['1:1']);
    expect(server.items).toEqual([{ name: 'Salt' }, { name: 'Pepper' }]);
  });

  it('chips cannot change while a save is in flight, so none is lost to its success', async () => {
    const { wrapper } = setup();
    const user = userEvent.setup();
    const served = mockedAuthFetch.getMockImplementation() as (u: string, o?: unknown) => Promise<unknown>;
    let answer!: () => void;
    const held = new Promise<void>((r) => { answer = r; });
    mockedAuthFetch.mockImplementation(async (url: string, opts?: { method?: string }) => {
      if (opts?.method === 'PUT') await held;
      return served(url, opts);
    });
    render(<PantryStaples />, { wrapper });
    await waitFor(() => expect(screen.getByText('Salt')).toBeInTheDocument());

    await user.type(screen.getByLabelText('New staple name'), 'Flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.click(screen.getByRole('button', { name: /save staples/i }));
    await waitFor(() => expect(sentTokens()).toEqual(['1:0']));

    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Remove Salt' })).toBeDisabled();
    await user.type(screen.getByLabelText('New staple name'), 'Rice{Enter}');
    expect(screen.queryByText('Rice')).not.toBeInTheDocument();

    await act(async () => { answer(); await held; });
    await waitFor(() => expect(screen.getByText('Saved')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Add' })).toBeEnabled();
    expect(server.items).toEqual([{ name: 'Salt' }, { name: 'Flour' }]);
  });
});
