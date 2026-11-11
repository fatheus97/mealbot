import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useEffect, useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as AuthCtx from '../contexts/AuthContext';
import { RestockPrompt } from './RestockPrompt';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import type { AuthState, RestockStatus } from '../types';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchRestockStatus: vi.fn(),
  answerRestockPrompt: vi.fn(),
}));

import { answerRestockPrompt, authFetch, fetchRestockStatus } from '../api';

const mockedFetch = vi.mocked(authFetch);
const mockedStatus = vi.mocked(fetchRestockStatus);
const mockedAnswer = vi.mocked(answerRestockPrompt);
const DUE: RestockStatus = { due: true, days_since_write: 23 };
const MESSAGE =
  "Your fridge list hasn't changed in 23 days. Start fresh from photos of your food and your recent receipts?";

/** GET /fridge as the server answers it: the list and its version token. */
const fridgeReply = (token: string | null = '1:3', status = 200) =>
  ({
    ok: status < 400,
    status,
    headers: new Headers(token ? { 'X-Fridge-Version': token } : {}),
    json: () => Promise.resolve([]),
  }) as Response;

function setAuth(over: Partial<AuthState> = {}) {
  vi.spyOn(AuthCtx, 'useAuth').mockReturnValue({
    userId: 1, onboardingCompleted: true, isDemo: false, ...over,
  } as unknown as AuthState);
}

let setOpen: (open: boolean) => void = () => {};

function renderPrompt({ restockOpen = false, cached }: { restockOpen?: boolean; cached?: RestockStatus } = {}) {
  const onStartRestock = vi.fn();
  // main.tsx's defaults (no focus refetch, 5 min fresh), so the focus test
  // below proves the hook's own SHARED options rather than the library's.
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: 300_000 },
      mutations: { retry: false },
    },
  });
  // Stale on purpose: an enabled query would refetch it on mount.
  if (cached) queryClient.setQueryData(['restock', 1], cached, { updatedAt: 0 });
  // MainLayout's half: Start fresh opens the dialog, which the prompt is told.
  function Harness() {
    const [open, setOpenState] = useState(restockOpen);
    useEffect(() => {
      setOpen = setOpenState;
    }, []);
    return (
      <RestockPrompt
        restockOpen={open}
        onStartRestock={() => {
          onStartRestock();
          setOpenState(true);
        }}
      />
    );
  }
  const view = render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
  return { ...view, onStartRestock, queryClient, reopen: (open: boolean) => act(() => setOpen(open)) };
}

/** Wait until the status GET has landed, so "no dialog" is not just "not yet". */
async function settled(queryClient: QueryClient) {
  await waitFor(() => expect(queryClient.getQueryState(['restock', 1])?.status).toBe('success'));
  await waitFor(() => expect(queryClient.getQueryState(['restock', 1])?.fetchStatus).toBe('idle'));
}

beforeEach(() => {
  mockedFetch.mockReset().mockResolvedValue(fridgeReply());
  mockedStatus.mockReset().mockResolvedValue(DUE);
  mockedAnswer.mockReset().mockResolvedValue({ due: false, days_since_write: null });
  setAuth();
});

afterEach(() => {
  // Unmount first: a re-render after the useAuth spy is gone would throw.
  cleanup();
  vi.restoreAllMocks();
  useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
});

describe('RestockPrompt', () => {
  it('asks with the day count when due; Not now answers and does not open the dialog', async () => {
    const user = userEvent.setup();
    const { onStartRestock } = renderPrompt();
    // The sentence is the dialog's description, so it is announced with the title.
    expect(
      await screen.findByRole('dialog', { name: 'Start fresh?', description: MESSAGE }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Not now' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedAnswer).toHaveBeenCalledTimes(1);
    expect(onStartRestock).not.toHaveBeenCalled();
  });

  it('Start fresh opens the restock dialog and answers exactly once', async () => {
    const user = userEvent.setup();
    const { onStartRestock, queryClient } = renderPrompt();
    await user.click(await screen.findByRole('button', { name: 'Start fresh' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onStartRestock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(queryClient.getQueryData<RestockStatus>(['restock', 1])?.due).toBe(false));
    expect(mockedAnswer).toHaveBeenCalledTimes(1);
  });

  it('Escape and a backdrop click count as Not now', async () => {
    const user = userEvent.setup();
    const first = renderPrompt();
    await screen.findByRole('dialog');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedAnswer).toHaveBeenCalledTimes(1);
    expect(first.onStartRestock).not.toHaveBeenCalled();
    first.unmount();

    const second = renderPrompt();
    fireEvent.mouseDown(await screen.findByRole('dialog'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(mockedAnswer).toHaveBeenCalledTimes(2));
    expect(second.onStartRestock).not.toHaveBeenCalled();
  });

  it('stays hidden when not due', async () => {
    mockedStatus.mockResolvedValue({ due: false, days_since_write: 3 });
    const { queryClient } = renderPrompt();
    await settled(queryClient);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('waits for the fridge list and its token, which the restock dialog reads at mount', async () => {
    let land: (reply: Response) => void = () => {};
    mockedFetch.mockReturnValue(new Promise<Response>((resolve) => { land = resolve; }));
    const { queryClient } = renderPrompt();
    await settled(queryClient);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => land(fridgeReply()));
    expect(await screen.findByRole('dialog', { name: 'Start fresh?' })).toBeInTheDocument();
  });

  it('never asks when the fridge GET failed or came without a token', async () => {
    mockedFetch.mockResolvedValue(fridgeReply('1:3', 500));
    const failed = renderPrompt();
    await settled(failed.queryClient);
    await waitFor(() => expect(failed.queryClient.getQueryState(['fridge', 1])?.status).toBe('error'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    failed.unmount();

    mockedFetch.mockResolvedValue(fridgeReply(null));
    const tokenless = renderPrompt();
    await settled(tokenless.queryClient);
    await waitFor(() => expect(tokenless.queryClient.getQueryState(['fridge', 1])?.status).toBe('success'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('a focus refetch in the same session does not ask again, even after a failed answer', async () => {
    mockedAnswer.mockRejectedValue(new Error('Restock answer failed: 500'));
    const user = userEvent.setup();
    const { queryClient } = renderPrompt();
    await user.click(await screen.findByRole('button', { name: 'Not now' }));
    await waitFor(() => expect(mockedAnswer).toHaveBeenCalledTimes(1));
    // The failed answer left due:true in the cache, and the server still says so.
    expect(queryClient.getQueryData<RestockStatus>(['restock', 1])?.due).toBe(true);

    await act(() => queryClient.invalidateQueries({ queryKey: ['restock'], refetchType: 'none' }));
    act(() => { window.dispatchEvent(new Event('visibilitychange')); });
    await waitFor(() => expect(mockedStatus).toHaveBeenCalledTimes(2));
    await settled(queryClient);
    expect(queryClient.getQueryData<RestockStatus>(['restock', 1])?.due).toBe(true);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('never asks or fetches for a demo account, even with a stale due in the cache', async () => {
    setAuth({ isDemo: true });
    renderPrompt({ cached: DUE });
    await act(async () => {});
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedStatus).not.toHaveBeenCalled();
  });

  it('never asks or fetches during onboarding, even with a stale due in the cache', async () => {
    setAuth({ onboardingCompleted: false });
    renderPrompt({ cached: DUE });
    await act(async () => {});
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedStatus).not.toHaveBeenCalled();
  });

  it('opening Start fresh another way answers once, so it does not nag after a remount', async () => {
    const { queryClient, reopen } = renderPrompt({ restockOpen: true });
    await settled(queryClient);
    await waitFor(() => expect(queryClient.getQueryData<RestockStatus>(['restock', 1])?.due).toBe(false));
    expect(mockedAnswer).toHaveBeenCalledTimes(1);

    await reopen(false);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('an open restock dialog hides it, and closing it does not ask, even if that answer failed', async () => {
    mockedAnswer.mockRejectedValue(new Error('Restock answer failed: 500'));
    const { queryClient, reopen } = renderPrompt({ restockOpen: true });
    await settled(queryClient);
    await waitFor(() => expect(queryClient.getQueryState(['fridge', 1])?.status).toBe('success'));
    await waitFor(() => expect(mockedAnswer).toHaveBeenCalledTimes(1));
    expect(queryClient.getQueryData<RestockStatus>(['restock', 1])?.due).toBe(true);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await reopen(false);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opening Start fresh when nothing is due answers nothing', async () => {
    mockedStatus.mockResolvedValue({ due: false, days_since_write: 3 });
    const { queryClient } = renderPrompt({ restockOpen: true });
    await settled(queryClient);
    await act(async () => {});
    expect(mockedAnswer).not.toHaveBeenCalled();
  });

  it('leaves no untranslated English in Czech', async () => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    const { container } = renderPrompt();
    expect(await screen.findByRole('dialog', { name: 'Začít nanovo?' })).toBeInTheDocument();
    expect(
      screen.getByText(
        'Seznam v lednici se nezměnil už 23 dní. Chcete ho sestavit znovu z fotek jídla a posledních účtenek?',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Začít nanovo' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Teď ne' })).toBeInTheDocument();
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });
});
