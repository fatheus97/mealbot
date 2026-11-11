import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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

import { answerRestockPrompt, fetchRestockStatus } from '../api';

const mockedStatus = vi.mocked(fetchRestockStatus);
const mockedAnswer = vi.mocked(answerRestockPrompt);
const DUE: RestockStatus = { due: true, days_since_write: 23 };
const MESSAGE =
  "Your fridge list hasn't changed in 23 days. Start fresh from photos of your food and your recent receipts?";

function setAuth(over: Partial<AuthState> = {}) {
  vi.spyOn(AuthCtx, 'useAuth').mockReturnValue({
    userId: 1, onboardingCompleted: true, isDemo: false, ...over,
  } as unknown as AuthState);
}

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
  if (cached) queryClient.setQueryData(['restock', 1], cached);
  const ui = (open: boolean) => (
    <QueryClientProvider client={queryClient}>
      <RestockPrompt restockOpen={open} onStartRestock={onStartRestock} />
    </QueryClientProvider>
  );
  const view = render(ui(restockOpen));
  return { ...view, onStartRestock, queryClient, reopen: (open: boolean) => view.rerender(ui(open)) };
}

/** Wait until the status GET has landed, so "no dialog" is not just "not yet". */
async function settled(queryClient: QueryClient) {
  await waitFor(() => expect(queryClient.getQueryState(['restock', 1])?.status).toBe('success'));
  await waitFor(() => expect(queryClient.getQueryState(['restock', 1])?.fetchStatus).toBe('idle'));
}

beforeEach(() => {
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
    expect(await screen.findByRole('dialog', { name: 'Start fresh?' })).toBeInTheDocument();
    expect(screen.getByText(MESSAGE)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Not now' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedAnswer).toHaveBeenCalledTimes(1);
    expect(onStartRestock).not.toHaveBeenCalled();
  });

  it('Start fresh answers too and opens the restock dialog', async () => {
    const user = userEvent.setup();
    const { onStartRestock } = renderPrompt();
    await user.click(await screen.findByRole('button', { name: 'Start fresh' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedAnswer).toHaveBeenCalledTimes(1);
    expect(onStartRestock).toHaveBeenCalledTimes(1);
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

  it('never asks or fetches for a demo account, even with due in the cache', async () => {
    setAuth({ isDemo: true });
    renderPrompt({ cached: DUE });
    await act(async () => {});
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedStatus).not.toHaveBeenCalled();
  });

  it('never asks or fetches during onboarding, even with due in the cache', async () => {
    setAuth({ onboardingCompleted: false });
    renderPrompt({ cached: DUE });
    await act(async () => {});
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mockedStatus).not.toHaveBeenCalled();
  });

  it('opening Start fresh another way counts as asked: closed again, it does not nag', async () => {
    const { queryClient, reopen } = renderPrompt({ restockOpen: true });
    await settled(queryClient);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    reopen(false);
    await settled(queryClient);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
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
