import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { StockItem, MealPlanRequest, MealPlanResponse, RegeneratePlanRequest, UserProfile } from '../types';
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
    mutationFn: (data: Partial<Pick<UserProfile, "country" | "measurement_system" | "variability" | "include_spices" | "onboarding_completed">>) =>
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

export function useGeneratePlan() {
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
    }
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