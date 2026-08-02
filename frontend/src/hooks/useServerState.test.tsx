import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFridge, useUserProfile, useUpdateFridge, useGeneratePlan, useRegeneratePlan, useConfirmPlan, usePlanCalendar, useReschedulePlan } from './useServerState';
import type { ReactNode } from 'react';

// Mock the api module
vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch, fetchUserProfile } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedFetchUserProfile = fetchUserProfile as ReturnType<typeof vi.fn>;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return {
    queryClient,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  };
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

describe('useFridge', () => {
  it('fetches fridge items when userId provided', async () => {
    const items = [{ name: 'Eggs', quantity_grams: 500, need_to_use: false }];
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(items),
    });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useFridge(1), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(items);
  });

  it('is disabled when userId is null', () => {
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useFridge(null), { wrapper });

    expect(result.current.fetchStatus).toBe('idle');
  });

  it('returns empty array on 404', async () => {
    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve(null),
    });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useFridge(1), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});

describe('useUserProfile', () => {
  it('fetches profile when userId provided', async () => {
    const profile = { id: 1, email: 'a@b.com', country: 'US' };
    mockedFetchUserProfile.mockResolvedValueOnce(profile);

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useUserProfile(1), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(profile);
  });

  it('is disabled when userId is null', () => {
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useUserProfile(null), { wrapper });

    expect(result.current.fetchStatus).toBe('idle');
  });
});

describe('useUpdateFridge', () => {
  it('sends PUT with items', async () => {
    const items = [{ name: 'Milk', quantity_grams: 1000, need_to_use: true }];
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(items),
    });

    const { wrapper, queryClient } = createWrapper();
    const setQueryDataSpy = vi.spyOn(queryClient, 'setQueryData');
    const { result } = renderHook(() => useUpdateFridge(), { wrapper });

    result.current.mutate({ userId: 1, items });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
      method: 'PUT',
      body: JSON.stringify(items),
    });
    expect(setQueryDataSpy).toHaveBeenCalledWith(['fridge', 1], items);
  });
});

describe('useGeneratePlan', () => {
  it('sends POST with days param', async () => {
    const plan = { plan_id: 1, days: [], shopping_list: [] };
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(plan),
    });

    const request = {
      ingredients: [],
      taste_preferences: [],
      avoid_ingredients: [],
      ingredients_to_use: [],
      diet_type: null,
      meals_per_day: 3,
      people_count: 2,
      past_meals: [],
    };

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useGeneratePlan(), { wrapper });

    result.current.mutate({ userId: 1, days: 3, request });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(plan);

    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan?days=3', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  });

  it('appends start_date to the query string when provided', async () => {
    const plan = { plan_id: 2, start_date: '2026-08-01', days: [], shopping_list: [] };
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(plan),
    });
    const request = {
      ingredients: [],
      taste_preferences: [],
      avoid_ingredients: [],
      ingredients_to_use: [],
      diet_type: null,
      meals_per_day: 1,
      people_count: 2,
      past_meals: [],
    };

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useGeneratePlan(), { wrapper });
    result.current.mutate({ userId: 1, days: 2, startDate: '2026-08-01', request });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan?days=2&start_date=2026-08-01', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  });

  it('surfaces the backend fail-closed allergen detail on a 422 (not the raw JSON body)', async () => {
    // The plan-creation path is the flagship allergen surface: when the screen
    // exhausts, the banner must show the friendly 422 `detail`, not `${status} -
    // ${rawBody}`. Guards against a revert to the raw-body dump.
    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: () => Promise.resolve({
        detail:
          "We couldn't generate a meal that avoids Milk (incl. lactose). Very " +
          "restrictive combinations can be hard to satisfy — try removing an " +
          "allergen or diet and generating again.",
      }),
    });
    const request = {
      ingredients: [], taste_preferences: [], avoid_ingredients: [],
      ingredients_to_use: [], diet_type: null, meals_per_day: 1,
      people_count: 2, past_meals: [],
    };
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useGeneratePlan(), { wrapper });
    result.current.mutate({ userId: 1, days: 1, request });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/try removing an allergen/i);
    // Not the raw-body format.
    expect(result.current.error?.message).not.toMatch(/^Plan generation failed: 422/);
  });

  it('surfaces the usage-cap 429 user_detail instead of "Please try again"', async () => {
    // This hook had its OWN copy of extractErrorDetail, which understood only a
    // string `detail`. So a capped user was told to retry — the one piece of
    // advice that cannot work here, for up to a month. The copy is gone; this
    // pins that the shared helper is what this path uses.
    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 429,
      json: () => Promise.resolve({
        detail: {
          user_detail:
            'You have used your €2.00 of AI generation for this month. Your ' +
            'allowance resets on 1 September 2026. New plans, recipes and ' +
            'receipt scanning are paused until then; everything you have ' +
            'already saved is unaffected.',
          code: 'usage_cap_reached',
          tier: 'paid',
          cap_eur: 2.0,
          reset_at: '2026-09-01T00:00:00',
        },
      }),
    });
    const request = {
      ingredients: [], taste_preferences: [], avoid_ingredients: [],
      ingredients_to_use: [], diet_type: null, meals_per_day: 1,
      people_count: 2, past_meals: [],
    };
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useGeneratePlan(), { wrapper });
    result.current.mutate({ userId: 1, days: 1, request });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/allowance resets on 1 September 2026/);
    expect(result.current.error?.message).not.toMatch(/Please try again/);
    expect(result.current.error?.message).not.toMatch(/usage_cap_reached|cap_eur/);
  });
});

describe('useConfirmPlan', () => {
  it('invalidates mealEntries cache so a re-confirm refetches new entries', async () => {
    // Repro for the un-confirm → regenerate → re-confirm regression: a
    // prior un-confirm cycle leaves an empty array cached under
    // ['mealEntries', planId]. If confirm doesn't invalidate that key,
    // per-meal cook buttons and rating UI never appear after re-confirm.
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });

    const { wrapper, queryClient } = createWrapper();
    queryClient.setQueryData(['mealEntries', 7], []);
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const { result } = renderHook(() => useConfirmPlan(), { wrapper });
    result.current.mutate({ planId: 7 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['mealEntries', 7] });
  });

  it('sends the chosen start_date in the confirm body', async () => {
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useConfirmPlan(), { wrapper });
    result.current.mutate({ planId: 9, startDate: '2026-08-01' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/9/confirm', {
      method: 'POST',
      body: JSON.stringify({ start_date: '2026-08-01' }),
    });
  });

  it('confirms with a null start_date body when the user picked no date', async () => {
    // authFetch always sends Content-Type: application/json, so we always send a
    // real body; null means "keep whatever date was set at generation".
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useConfirmPlan(), { wrapper });
    result.current.mutate({ planId: 3 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/3/confirm', {
      method: 'POST',
      body: JSON.stringify({ start_date: null }),
    });
  });

  it('coerces a cleared date ("") to null (empty string would 422 as an invalid date)', async () => {
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useConfirmPlan(), { wrapper });
    result.current.mutate({ planId: 4, startDate: '' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/4/confirm', {
      method: 'POST',
      body: JSON.stringify({ start_date: null }),
    });
  });
});

describe('useRegeneratePlan', () => {
  it('sends POST with frozen meals', async () => {
    const plan = { plan_id: 1, days: [], shopping_list: [] };
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(plan),
    });

    const request = { frozen_meals: [{ day_index: 0, meal_index: 1 }] };

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useRegeneratePlan(), { wrapper });

    result.current.mutate({ planId: 5, request });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/5/regenerate', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  });

  it('surfaces the backend fail-closed allergen detail on a 422 (not the raw JSON body)', async () => {
    // Same guard for the regenerate path, which also runs the allergen screen.
    mockedAuthFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: () => Promise.resolve({
        detail:
          "We couldn't generate a meal that avoids Fish. Very restrictive " +
          "combinations can be hard to satisfy — try removing an allergen or " +
          "diet and generating again.",
      }),
    });
    const request = { frozen_meals: [{ day_index: 0, meal_index: 1 }] };
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useRegeneratePlan(), { wrapper });
    result.current.mutate({ planId: 5, request });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/try removing an allergen/i);
    expect(result.current.error?.message).not.toMatch(/^Regeneration failed: 422/);
  });
});

describe('usePlanCalendar', () => {
  it('fetches the calendar for the given window', async () => {
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ plans: [] }),
    });
    const { wrapper } = createWrapper();
    const { result } = renderHook(
      () => usePlanCalendar(1, '2026-08-01', '2026-08-31'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith(
      '/plan/calendar?from=2026-08-01&to=2026-08-31',
    );
  });

  it('is disabled (no fetch) without a userId', () => {
    mockedAuthFetch.mockClear();
    const { wrapper } = createWrapper();
    const { result } = renderHook(
      () => usePlanCalendar(null, '2026-08-01', '2026-08-31'),
      { wrapper },
    );
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockedAuthFetch).not.toHaveBeenCalled();
  });
});

describe('useReschedulePlan', () => {
  it('PATCHes the plan with the new start_date', async () => {
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ plan_id: 9, start_date: '2026-08-20' }),
    });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useReschedulePlan(), { wrapper });
    result.current.mutate({ planId: 9, startDate: '2026-08-20' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/9', {
      method: 'PATCH',
      body: JSON.stringify({ start_date: '2026-08-20' }),
    });
  });

  it('sends null to unschedule', async () => {
    mockedAuthFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ plan_id: 9, start_date: null }),
    });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useReschedulePlan(), { wrapper });
    result.current.mutate({ planId: 9, startDate: null });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedAuthFetch).toHaveBeenCalledWith('/plan/9', {
      method: 'PATCH',
      body: JSON.stringify({ start_date: null }),
    });
  });
});
