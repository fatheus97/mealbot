import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFridge, useUserProfile, useUpdateFridge, useGeneratePlan, useRegeneratePlan } from './useServerState';
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
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateFridge(), { wrapper });

    result.current.mutate({ userId: 1, items });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedAuthFetch).toHaveBeenCalledWith('/fridge', {
      method: 'PUT',
      body: JSON.stringify(items),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['fridge', 1] });
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
});
