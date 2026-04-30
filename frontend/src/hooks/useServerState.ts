import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { StockItem, MealPlanRequest, MealPlanResponse, MealPlanSummary, MealEntrySummary, RegeneratePlanRequest, UserProfile, FinishPlanResponse, SingleRecipeRequest, CookRecipeRequest, FavoriteRecipeRequest, CookbookListResponse, CookbookCountResponse } from '../types';
import { authFetch, cookRecipe, favoriteRecipe, fetchUserProfile, generateRecipe, mergeFridgeItems, scanReceipt, updateUserProfile } from '../api';

// --- Queries (Data Fetching) ---

export function useFridge(userId: number | null) {
  return useQuery({
    queryKey: ['fridge', userId],
    queryFn: async (): Promise<StockItem[]> => {
      const res = await authFetch(`/fridge`);
      if (res.status === 404) return [];
      if (!res.ok) throw new Error(`Fridge fetch failed: ${res.status}`);
      return res.json();
    },
    enabled: userId !== null,
  });
}

export function useUserProfile(userId: number | null) {
  return useQuery({
    queryKey: ['userProfile', userId],
    queryFn: fetchUserProfile,
    enabled: userId !== null,
  });
}

// --- Mutations (Data Manipulation) ---

export function useUpdateUserProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: Partial<Pick<UserProfile, "country" | "language" | "measurement_system" | "variability" | "include_spices" | "track_snacks" | "onboarding_completed" | "default_day_layout">>) =>
      updateUserProfile(data),
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: ['userProfile'] });
    },
  });
}

export function useGenerateRecipe() {
  return useMutation({
    mutationFn: (payload: SingleRecipeRequest) => generateRecipe(payload),
  });
}

export function useCookRecipe() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CookRecipeRequest) => cookRecipe(payload),
    onSuccess: () => {
      // Fridge is debited and a new 1-day plan row is created. Invalidate
      // both so the sidebar catalog (usePlanList → ['planList']) and the
      // fridge UI (useFridge → ['fridge']) pick up the side effects.
      // MealEntry queries are keyed by planId so there's no cross-plan
      // cache to invalidate here.
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
      queryClient.invalidateQueries({ queryKey: ['planList'] });
    },
  });
}

export function useUpdateFridge() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ items }: { userId: number; items: StockItem[] }) => {
      const res = await authFetch(`/fridge`, {
        method: "PUT",
        body: JSON.stringify(items),
      });
      if (!res.ok) throw new Error(`Fridge update failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (data, variables) => {
      queryClient.setQueryData(['fridge', variables.userId], data);
    },
  });
}

export function useScanReceipt() {
  return useMutation({
    mutationFn: (file: File) => scanReceipt(file),
  });
}

export function useMergeFridge() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (items: StockItem[]) => mergeFridgeItems(items),
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: ['fridge'] });
    },
  });
}

export function usePlanList(userId: number | null) {
  return useQuery({
    queryKey: ['planList', userId],
    queryFn: async (): Promise<MealPlanSummary[]> => {
      const res = await authFetch('/plan');
      if (!res.ok) throw new Error(`Plan list fetch failed: ${res.status}`);
      return res.json();
    },
    enabled: userId !== null,
  });
}

export function useMealEntries(planId: number | null) {
  return useQuery({
    queryKey: ['mealEntries', planId],
    queryFn: async (): Promise<MealEntrySummary[]> => {
      const res = await authFetch(`/plan/${planId}/meals`);
      if (!res.ok) throw new Error(`Meal entries fetch failed: ${res.status}`);
      return res.json();
    },
    enabled: planId !== null,
  });
}

export function useDeletePlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (planId: number) => {
      const res = await authFetch(`/plan/${planId}`, { method: "DELETE" });
      // Backend now returns 409 with a detail message when the plan contains
      // cookbook entries. Use extractErrorDetail (same as useUnconfirmPlan /
      // useReopenPlan) so the user sees "This plan contains N cookbook
      // recipes…" instead of a bare status code.
      if (!res.ok) throw new Error(await extractErrorDetail(res, "Plan delete failed"));
    },
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: ['planList'] });
    },
  });
}

export function useConfirmPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (planId: number): Promise<StockItem[]> => {
      const res = await authFetch(`/plan/${planId}/confirm`, { method: "POST" });
      if (!res.ok) throw new Error(`Confirm failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (_, planId) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
      // Confirm creates the meal entry rows server-side. Without this,
      // an un-confirm → regenerate → re-confirm cycle leaves the cache
      // holding the empty array refetched during un-confirm, so per-meal
      // cook buttons and rating UI never appear.
      queryClient.invalidateQueries({ queryKey: ['mealEntries', planId] });
    },
  });
}

export function useCookMeal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ planId, mealEntryId }: { planId: number; mealEntryId: number }): Promise<MealEntrySummary> => {
      const res = await authFetch(`/plan/${planId}/meals/${mealEntryId}/cook`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`Cook meal failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['mealEntries', variables.planId] });
    },
  });
}

export function useUncookMeal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ planId, mealEntryId }: { planId: number; mealEntryId: number }): Promise<MealEntrySummary> => {
      const res = await authFetch(`/plan/${planId}/meals/${mealEntryId}/uncook`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`Uncook meal failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['mealEntries', variables.planId] });
    },
  });
}

// Toggle cookbook membership for an existing plan meal entry. Server flips
// the embedding to match (added on True, cleared on False). The cookbook
// list/count caches are invalidated so the FAB badge and modal stay live.
export function useFavoriteMeal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ planId, mealEntryId, isFavorite }: { planId: number; mealEntryId: number; isFavorite: boolean }): Promise<MealEntrySummary> => {
      const res = await authFetch(`/plan/${planId}/meals/${mealEntryId}/favorite`, {
        method: "POST",
        body: JSON.stringify({ is_favorite: isFavorite }),
      });
      if (!res.ok) throw new Error(`Favorite toggle failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['mealEntries', variables.planId] });
      queryClient.invalidateQueries({ queryKey: ['cookbook'] });
      queryClient.invalidateQueries({ queryKey: ['cookbookCount'] });
    },
  });
}

// Star a Cook Now recipe straight into the cookbook (creates the MealEntry).
// Used when the user clicks ★ on a freshly generated recipe before any cook
// action — server creates a kind="cook_now" plan and a MealEntry with
// is_favorite=True and cooked_at=NULL.
export function useFavoriteRecipe() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: FavoriteRecipeRequest) => favoriteRecipe(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cookbook'] });
      queryClient.invalidateQueries({ queryKey: ['cookbookCount'] });
    },
  });
}

interface UseCookbookParams {
  q?: string;
  mealType?: string;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function useCookbook({ q, mealType, limit = 50, offset = 0, enabled = true }: UseCookbookParams = {}) {
  return useQuery({
    queryKey: ['cookbook', { q, mealType, limit, offset }],
    queryFn: async (): Promise<CookbookListResponse> => {
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      if (mealType) params.set('meal_type', mealType);
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      const res = await authFetch(`/cookbook?${params.toString()}`);
      if (!res.ok) throw new Error(`Cookbook fetch failed: ${res.status}`);
      return res.json();
    },
    enabled,
  });
}

export function useCookbookCount(userId: number | null) {
  return useQuery({
    queryKey: ['cookbookCount', userId],
    queryFn: async (): Promise<CookbookCountResponse> => {
      const res = await authFetch('/cookbook/count');
      if (!res.ok) throw new Error(`Cookbook count failed: ${res.status}`);
      return res.json();
    },
    enabled: userId !== null,
    staleTime: 30_000,
  });
}

export function useRemoveFromCookbook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (mealEntryId: number): Promise<CookbookCountResponse> => {
      const res = await authFetch(`/cookbook/${mealEntryId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`Remove from cookbook failed: ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cookbook'] });
      queryClient.invalidateQueries({ queryKey: ['cookbookCount'] });
      // The plan-side meals query holds is_favorite, so the star next to a
      // meal in the plan view re-syncs to false after a delete from the
      // cookbook modal.
      queryClient.invalidateQueries({ queryKey: ['mealEntries'] });
    },
  });
}

// Reads the FastAPI `detail` field on non-OK responses so 409s surface
// useful messages (e.g. "Not enough chicken in fridge to reopen...") instead
// of a bare status code. Falls back to the status if the body isn't JSON.
async function extractErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    // body wasn't JSON — fall through
  }
  return `${fallback}: ${res.status}`;
}

export function useUnconfirmPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (planId: number): Promise<StockItem[]> => {
      const res = await authFetch(`/plan/${planId}/unconfirm`, { method: "POST" });
      if (!res.ok) throw new Error(await extractErrorDetail(res, "Un-confirm failed"));
      return res.json();
    },
    onSuccess: (_, planId) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
      // Server deletes all meal entries; clear the cache so any reader
      // outside the isConfirmed gate doesn't see stale rows.
      queryClient.invalidateQueries({ queryKey: ['mealEntries', planId] });
    },
  });
}

export function useReopenPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (planId: number): Promise<StockItem[]> => {
      const res = await authFetch(`/plan/${planId}/reopen`, { method: "POST" });
      if (!res.ok) throw new Error(await extractErrorDetail(res, "Reopen failed"));
      return res.json();
    },
    onSuccess: (_, planId) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
      // Reopen rewrites consumed_snapshot_json on uncooked entries; the
      // cached MealEntrySummary doesn't expose it, but invalidate for
      // consistency with other plan-state mutations.
      queryClient.invalidateQueries({ queryKey: ['mealEntries', planId] });
    },
  });
}

export function useFinishPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (planId: number): Promise<FinishPlanResponse> => {
      const res = await authFetch(`/plan/${planId}/finish`, { method: "POST" });
      if (!res.ok) throw new Error(`Finish plan failed: ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
    },
  });
}

export function useGeneratePlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ days, request }: { userId: number; days: number; request: MealPlanRequest }): Promise<MealPlanResponse> => {
      const res = await authFetch(`/plan?days=${days}`, {
        method: "POST",
        body: JSON.stringify(request),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Plan generation failed: ${res.status} - ${txt}`);
      }
      return res.json();
    },
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: ['planList'] });
    },
  });
}

export function useRegeneratePlan() {
  return useMutation({
    mutationFn: async ({
      planId,
      request,
    }: {
      planId: number;
      request: RegeneratePlanRequest;
    }): Promise<MealPlanResponse> => {
      const res = await authFetch(`/plan/${planId}/regenerate`, {
        method: "POST",
        body: JSON.stringify(request),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Regeneration failed: ${res.status} - ${txt}`);
      }
      return res.json();
    },
  });
}