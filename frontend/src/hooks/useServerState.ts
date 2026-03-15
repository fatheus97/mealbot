import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { StockItem, MealPlanRequest, MealPlanResponse, MealPlanSummary, MealEntrySummary, RegeneratePlanRequest, UserProfile, FinishPlanResponse } from '../types';
import { authFetch, fetchUserProfile, mergeFridgeItems, scanReceipt, updateUserProfile } from '../api';

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
    mutationFn: (data: Partial<Pick<UserProfile, "country" | "language" | "measurement_system" | "variability" | "include_spices" | "track_snacks" | "onboarding_completed">>) =>
      updateUserProfile(data),
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: ['userProfile'] });
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
    onSuccess: (_, variables) => {
      return queryClient.invalidateQueries({ queryKey: ['fridge', variables.userId] });
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
      if (!res.ok) throw new Error(`Plan delete failed: ${res.status}`);
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
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

export function useRateMeal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ planId, mealEntryId, rating }: { planId: number; mealEntryId: number; rating: number }): Promise<MealEntrySummary> => {
      const res = await authFetch(`/plan/${planId}/meals/${mealEntryId}/rate`, {
        method: "POST",
        body: JSON.stringify({ rating }),
      });
      if (!res.ok) throw new Error(`Rate meal failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['mealEntries', variables.planId] });
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