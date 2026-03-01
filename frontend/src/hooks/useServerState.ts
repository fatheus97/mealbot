import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { StockItem, MealPlanRequest, MealPlanResponse } from '../types';

const API_BASE = "http://localhost:8000/api";

// --- Queries (Data Fetching) ---

export function useFridge(userId: number | null) {
  return useQuery({
    queryKey: ['fridge', userId],
    queryFn: async (): Promise<StockItem[]> => {
      const res = await fetch(`${API_BASE}/users/${userId}/fridge`);
      if (res.status === 404) return [];
      if (!res.ok) throw new Error(`Fridge fetch failed: ${res.status}`);
      return res.json();
    },
    enabled: userId !== null, // Only fetch if we have a valid user
  });
}

// --- Mutations (Data Manipulation) ---

export function useUpdateFridge() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, items }: { userId: number; items: StockItem[] }) => {
      const res = await fetch(`${API_BASE}/users/${userId}/fridge`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
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

export function useGeneratePlan() {
  return useMutation({
    mutationFn: async ({ userId, days, request }: { userId: number; days: number; request: MealPlanRequest }): Promise<MealPlanResponse> => {
      const res = await fetch(`${API_BASE}/users/${userId}/plan?days=${days}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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