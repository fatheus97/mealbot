import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import type { StockItem, PantryStaple, MealPlanRequest, MealPlanResponse, MealPlanSummary, MealEntrySummary, MealEditRequest, MealEditResponse, RegeneratePlanRequest, UserProfile, FinishPlanResponse, PlanScheduleResponse, CalendarResponse, SingleRecipeRequest, CookRecipeRequest, FavoriteRecipeRequest, CookbookListResponse, CookbookCountResponse, AdminUserUpdate, InviteCreateRequest, FeedbackCreateRequest, FeedbackModerationStatus, AccessRequestStatus, ScanSource, WasteEntry } from '../types';
import { acceptAdminFeedback, authFetch, cookRecipe, createAdminUser, createInvite, deleteAccessRequest, fetchAccessRequests, updateAccessRequest, deleteAdminUser, favoriteRecipe, fetchAdminFeedback, fetchAdminFeedbackDetail, fetchInvites, fetchPolicyNotice, fetchUserProfile, forceLogoutAdminUser, generateRecipe, mergeFridgeItems, PaywallError, resetAdminUserOnboarding, retriageAdminFeedback, revokeInvite, recordWaste, scanReceipt, sendPolicyNotice, submitFeedback, updateAdminFeedback, updateAdminUser, updateMeal, updateUserProfile, verifyAdminUserEmail, type AdminFeedbackQuery } from '../api';
import { extractErrorDetail } from '../utils/httpError';

// --- Queries (Data Fetching) ---

// Queries a household member can change from another phone: refetched when the
// window regains focus, so a partner's edit shows up without a reload. The
// app-wide default (main.tsx) is 5 min and no focus refetch.
const SHARED = { refetchOnWindowFocus: true, staleTime: 30_000 } as const;

// The fridge and the staples are each saved as a whole list, so a save made
// from an out-of-date copy would overwrite a partner's change. The server
// counts every write and hands out a version token, `<household>:<count>`; a
// PUT carrying an old one is refused with 409 and writes nothing.
const SHELVES = {
  fridge: { path: '/fridge', header: 'X-Fridge-Version', label: 'Fridge' },
  staples: { path: '/staples', header: 'X-Staples-Version', label: 'Staples' },
} as const;
type Shelf = keyof typeof SHELVES;

/** Identifies a shelf's saves, for a component that must wait for them. */
export const shelfSaveKey = (shelf: Shelf) => [shelf, 'put'] as const;

/** A shelf as cached: the list and the token it was read or written at. null
 *  when the server sent none. Components see only `items` (the queries select
 *  it). */
export interface ShelfData<T> {
  items: T[];
  token: string | null;
}

/** The server refused a save because the list changed since it was loaded
 *  (409 fridge_changed / staples_changed). The message is the server's
 *  localized sentence; the hook has already reloaded the list. */
export class ShelfChangedError extends Error {}

/** The cached list and its token, read together: what a save must send is the
 *  token of the very list its items were made from. */
export function cachedShelf<T>(
  queryClient: QueryClient,
  shelf: Shelf,
  userId: number,
): ShelfData<T> | undefined {
  return queryClient.getQueryData<ShelfData<T>>([shelf, userId]);
}

function itemsOf<T>(data: ShelfData<T>): T[] {
  return data.items;
}

function useShelf<T>(shelf: Shelf, userId: number | null) {
  const { path, header, label } = SHELVES[shelf];
  return useQuery({
    queryKey: [shelf, userId],
    queryFn: async (): Promise<ShelfData<T>> => {
      const res = await authFetch(path);
      if (res.status === 404) return { items: [], token: null };
      if (!res.ok) throw new Error(`${label} fetch failed: ${res.status}`);
      // Optional chaining: test doubles of Response often carry no headers.
      return { items: (await res.json()) as T[], token: res.headers?.get(header) ?? null };
    },
    select: itemsOf<T>,
    enabled: userId !== null,
    ...SHARED,
  });
}

interface ShelfSave<T> {
  userId: number;
  items: T[];
  /** The token of the list these items were made from. */
  token: string | null;
}

function useUpdateShelf<T>(shelf: Shelf) {
  const queryClient = useQueryClient();
  const { path, header, label } = SHELVES[shelf];
  // This caller's last accepted save. A save it made from the same list before
  // that one returned carries that one's edits too (the caller's copy has them),
  // so it follows it, with the token that save got back. It is per caller on
  // purpose: a save from another component is NOT in this caller's list, so its
  // token must not be adopted, and the server refuses the old one instead.
  const lastSave = useRef<{ base: string | null; latest: string | null } | null>(null);

  return useMutation({
    mutationKey: shelfSaveKey(shelf),
    // One save at a time per shelf, across every component: each waits for the
    // previous one to return, so two quick edits on one phone never refuse each
    // other.
    scope: { id: shelf },
    mutationFn: async ({ items, token }: ShelfSave<T>): Promise<ShelfData<T>> => {
      const sent = lastSave.current?.base === token ? lastSave.current.latest : token;
      const res = await authFetch(path, {
        method: "PUT",
        body: JSON.stringify(items),
        // No header at all without a token (accepted, like an older bundle).
        ...(sent !== null ? { headers: { [header]: sent } } : {}),
      });
      if (res.status === 409) {
        throw new ShelfChangedError(await extractErrorDetail(res, `${label} update refused`));
      }
      if (!res.ok) throw new Error(`${label} update failed: ${res.status}`);
      return { items: (await res.json()) as T[], token: res.headers?.get(header) ?? null };
    },
    onSuccess: async (data, { userId, token }) => {
      lastSave.current = { base: token, latest: data.token };
      const key = [shelf, userId];
      // A GET that left before this save must not land after it and roll it back.
      await queryClient.cancelQueries({ queryKey: key });
      queryClient.setQueryData<ShelfData<T>>(key, data);
    },
    onError: (error, { userId }) => {
      // Not awaited, or this save would hold the queue until the GET settles. A
      // GET that failed on a hidden page waits for focus, focus first waits for
      // queued saves (resumePausedMutations), and nothing would ever move again.
      if (error instanceof ShelfChangedError) {
        void queryClient.invalidateQueries({ queryKey: [shelf, userId] });
      }
    },
  });
}

export function useFridge(userId: number | null) {
  return useShelf<StockItem>('fridge', userId);
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
    mutationFn: (data: Partial<Pick<UserProfile, "country" | "language" | "measurement_system" | "variability" | "include_spices" | "track_snacks" | "show_pieces" | "need_to_use_enabled" | "waste_tracking_enabled" | "onboarding_completed" | "default_day_layout">>) =>
      updateUserProfile(data),
    onSuccess: () => {
      // ['fridge'] too: need_to_use_enabled changes what GET /fridge masks, and
      // with a 30 s staleTime (SHARED) the cached fridge would otherwise keep
      // serving the PRE-toggle masking until the next focus refetch. That's not just cosmetic — Fridge.tsx's persistFridge PUTs
      // its entire local array back on any edit, so an edit against that stale
      // cache would write the wrong-masking values as the new stored truth.
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: ['userProfile'] }),
        queryClient.invalidateQueries({ queryKey: ['fridge'] }),
      ]);
    },
  });
}

/**
 * Post "ate it / threw it out" answers.
 *
 * Invalidates NOTHING: WasteRecord is write-only today, so no query in the app
 * reads it and there is no cache that could go stale. Add invalidation with the
 * first consumer, not before.
 */
export function useRecordWaste() {
  return useMutation({
    mutationFn: (entries: WasteEntry[]) => recordWaste(entries),
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
  return useUpdateShelf<StockItem>('fridge');
}

export function useScanReceipt() {
  return useMutation({
    mutationFn: ({ file, source }: { file: File; source: ScanSource }) => scanReceipt(file, source),
  });
}

// Pantry staples — the per-user "always have" list, excluded from generated
// shopping lists. Same shelf plumbing as the fridge; the PUT primes the cache
// so the panel stays in sync.
export function useStaples(userId: number | null) {
  return useShelf<PantryStaple>('staples', userId);
}

export function useUpdateStaples() {
  return useUpdateShelf<PantryStaple>('staples');
}

export function useMergeFridge() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (vars: { items: StockItem[]; generationId: number | null }) =>
      mergeFridgeItems(vars.items, vars.generationId),
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
    ...SHARED,
  });
}

// Scheduled plans overlapping [from, to] (YYYY-MM-DD), for the calendar grid.
export function usePlanCalendar(
  userId: number | null,
  from: string,
  to: string,
) {
  return useQuery({
    queryKey: ['planCalendar', userId, from, to],
    queryFn: async (): Promise<CalendarResponse> => {
      const res = await authFetch(`/plan/calendar?from=${from}&to=${to}`);
      if (!res.ok) throw new Error(`Calendar fetch failed: ${res.status}`);
      return res.json();
    },
    // Always refetch when the calendar (re)opens. The app-wide default is a
    // 5-min staleTime (main.tsx), which otherwise leaves the calendar showing a
    // stale month for minutes after a plan is confirmed/rescheduled elsewhere.
    staleTime: 0,
    refetchOnWindowFocus: SHARED.refetchOnWindowFocus,
    enabled: userId !== null && !!from && !!to,
  });
}

// Reschedule (or unschedule, with start_date null) a plan's calendar date.
export function useReschedulePlan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ planId, startDate }: { planId: number; startDate: string | null }): Promise<PlanScheduleResponse> => {
      const res = await authFetch(`/plan/${planId}`, {
        method: "PATCH",
        body: JSON.stringify({ start_date: startDate }),
      });
      if (!res.ok) throw new Error(`Reschedule failed: ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['planCalendar'] });
    },
  });
}

// "Repeat this week": copy a plan's meals onto a new start date. No LLM call,
// so this returns immediately and costs nothing — but it DOES create a plan, so
// the catalog and calendar both have to re-fetch, same as a reschedule.
//
// The copy comes back UNCONFIRMED, which means it will not appear in the plan
// catalog (that list is confirmed-only) until the user confirms it. The caller
// is responsible for saying so; a silent success on a screen where nothing
// visibly changes reads as a no-op.
/** A plan action the server refused for a reason the user can act on (a 403
 *  gate, such as missing consent for diet data, a 409, such as a plan whose
 *  diet data was removed, or a 422 that explains itself, such as too many
 *  ingredients to avoid for everyone eating); its message is the server's
 *  localized explanation, safe to show as is. */
export class PlanActionRefusedError extends Error {}

export function useRepeatPlan() {
  return useMutation({
    mutationFn: async ({ planId, startDate }: { planId: number; startDate: string | null }): Promise<MealPlanResponse> => {
      const res = await authFetch(`/plan/${planId}/repeat`, {
        method: "POST",
        body: JSON.stringify({ start_date: startDate }),
      });
      if (res.status === 403 || res.status === 409) {
        throw new PlanActionRefusedError(await extractErrorDetail(res, "Repeat failed"));
      }
      if (res.status === 422) {
        // The server's own 422s carry a sentence; a body-validation 422 (a bad
        // date) carries a list and keeps the generic message below.
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        if (typeof body?.detail === "string") throw new PlanActionRefusedError(body.detail);
      }
      if (!res.ok) throw new Error(`Repeat failed: ${res.status}`);
      return res.json();
    },
    // No invalidation, deliberately. Both `planList` and `planCalendar` filter
    // `confirmed_at IS NOT NULL` server-side (plan.py:130 and :211), and a
    // repeat copy is ALWAYS created unconfirmed — so neither query's result can
    // change, and invalidating them would fire two refetches that are
    // guaranteed to return what they already had. The copy becomes visible in
    // both the moment the user confirms it in the planner, and the confirm path
    // already invalidates.
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
      // A delete removes the plan from calendar eligibility too — refresh it
      // (belt-and-suspenders with usePlanCalendar's staleTime:0).
      queryClient.invalidateQueries({ queryKey: ['planCalendar'] });
      // Deleting an unfinished plan returns its uncooked meals' food.
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
      return queryClient.invalidateQueries({ queryKey: ['planList'] });
    },
  });
}

export function useConfirmPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ planId, startDate }: { planId: number; startDate?: string | null }): Promise<StockItem[]> => {
      // Always send a JSON body. The backend body is optional, but authFetch sets
      // Content-Type: application/json unconditionally, so a bodyless POST would
      // still carry that header with an empty payload. `|| null` coerces BOTH
      // undefined AND "" (the date input cleared) to null: a null start_date is
      // a no-op server-side (keeps any date set at generation), whereas "" would
      // be rejected as an invalid date (422).
      const res = await authFetch(`/plan/${planId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ start_date: startDate || null }),
      });
      if (!res.ok) throw new Error(`Confirm failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (_, { planId }) => {
      queryClient.invalidateQueries({ queryKey: ['planList'] });
      queryClient.invalidateQueries({ queryKey: ['fridge'] });
      // A confirm is what makes a scheduled plan appear on the calendar, so
      // refresh it too (belt-and-suspenders alongside usePlanCalendar's
      // staleTime:0 — covers the case where the calendar is already mounted).
      queryClient.invalidateQueries({ queryKey: ['planCalendar'] });
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

// Save a Cook Now recipe straight into the cookbook (creates the MealEntry).
// Used when the user taps the heart on a freshly generated recipe before any cook
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
    ...SHARED,
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
    ...SHARED,
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
      // Un-confirm clears confirmed_at, which /plan/calendar filters on, so the
      // plan drops off the calendar — refresh it (with usePlanCalendar's staleTime:0).
      queryClient.invalidateQueries({ queryKey: ['planCalendar'] });
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
    mutationFn: async ({ days, startDate, request }: { userId: number; days: number; startDate?: string | null; request: MealPlanRequest }): Promise<MealPlanResponse> => {
      const dateParam = startDate ? `&start_date=${startDate}` : "";
      const res = await authFetch(`/plan?days=${days}${dateParam}`, {
        method: "POST",
        body: JSON.stringify(request),
      });
      if (res.status === 402) throw new PaywallError();
      if (!res.ok) {
        // Surface the backend `detail` — including the fail-closed allergen
        // 422 — instead of dumping the raw JSON body into the error banner.
        throw new Error(await extractErrorDetail(res, "Plan generation failed. Please try again."));
      }
      return res.json();
    },
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: ['planList'] });
    },
  });
}

// Edit one meal's content in place. Addressed positionally (0-based day/meal),
// which works pre- and post-confirm. Server keeps response_json and (once
// confirmed) the MealEntry in sync, so we invalidate the meal-entry and
// cookbook caches — a favorited meal's name may have changed.
export function useUpdateMeal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, dayIndex, mealIndex, body }: {
      planId: number;
      dayIndex: number;
      mealIndex: number;
      body: MealEditRequest;
    }): Promise<MealEditResponse> => updateMeal(planId, dayIndex, mealIndex, body),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['mealEntries', variables.planId] });
      queryClient.invalidateQueries({ queryKey: ['cookbook'] });
      queryClient.invalidateQueries({ queryKey: ['cookbookCount'] });
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
      if (res.status === 402) throw new PaywallError();
      if (!res.ok) {
        // Surface the backend `detail` — including the fail-closed allergen
        // 422 — instead of dumping the raw JSON body into the error banner.
        throw new Error(await extractErrorDetail(res, "Regeneration failed. Please try again."));
      }
      return res.json();
    },
  });
}

// --- Admin: user management (every endpoint is 403-gated server-side; each
// mutation invalidates the ['admin','users'] list so the table refetches) ---

export function useCreateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    // Wrap (rather than passing createAdminUser bare) so react-query's second
    // mutationFn context arg isn't forwarded to the api helper — consistent with
    // the update/reset/logout hooks below.
    mutationFn: (body: { email: string; password: string; is_admin?: boolean; is_comped?: boolean }) =>
      createAdminUser(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useUpdateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, update }: { id: number; update: AdminUserUpdate }) =>
      updateAdminUser(id, update),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useResetAdminUserOnboarding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => resetAdminUserOnboarding(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useVerifyAdminUserEmail() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => verifyAdminUserEmail(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useForceLogoutAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => forceLogoutAdminUser(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

export function useDeleteAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteAdminUser(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

// --- Admin: invite links (each mutation invalidates ['admin','invites']) ---

export function useInvites(enabled: boolean) {
  return useQuery({
    queryKey: ['admin', 'invites'],
    queryFn: fetchInvites,
    enabled,
  });
}

export function useCreateInvite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: InviteCreateRequest) => createInvite(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'invites'] }),
  });
}

export function useRevokeInvite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => revokeInvite(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'invites'] }),
  });
}

// --- Policy-change notice email (admin "Notices" tab) ---

export function usePolicyNotice(enabled: boolean) {
  return useQuery({
    queryKey: ['admin', 'policy-notice'],
    queryFn: fetchPolicyNotice,
    enabled,
  });
}

export function useSendPolicyNotice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (confirmRecipients: number) => sendPolicyNotice(confirmRecipients),
    // The sends run in the background on the server, so this refetch only
    // shows the first of them; the panel offers a Refresh for the rest.
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['admin', 'policy-notice'] }),
  });
}

// --- Access requests (admin triage of the public landing form) ---

export function useAccessRequests(enabled: boolean, status?: AccessRequestStatus) {
  return useQuery({
    queryKey: ['admin', 'access-requests', status ?? 'all'],
    queryFn: () => fetchAccessRequests(status),
    enabled,
  });
}

export function useUpdateAccessRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: "handled" | "dismissed" }) =>
      updateAccessRequest(id, status),
    // Every status filter shares the prefix, so one invalidate refreshes the
    // list whichever tab the admin is on (and the pending badge with it).
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'access-requests'] }),
  });
}

export function useDeleteAccessRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteAccessRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'access-requests'] }),
  });
}

// --- User feedback: submit (any logged-in user) + admin moderation ---

export function useSubmitFeedback() {
  return useMutation({
    mutationFn: (body: FeedbackCreateRequest) => submitFeedback(body),
  });
}

// The admin moderation queue. Keyed on the query so status/kind/page changes
// refetch; disabled until the tab is active (enabled) to keep it lazy.
export function useAdminFeedback(query: AdminFeedbackQuery, enabled: boolean) {
  return useQuery({
    queryKey: ['admin', 'feedback', query],
    queryFn: () => fetchAdminFeedback(query),
    enabled,
  });
}

export function useAdminFeedbackDetail(id: number | null) {
  return useQuery({
    queryKey: ['admin', 'feedback', 'detail', id],
    queryFn: () => fetchAdminFeedbackDetail(id as number),
    enabled: id !== null,
  });
}

// Both mutations invalidate the list AND the open detail so the queue and the
// drawer re-sync after a status change / re-triage.
export function useModerateFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: FeedbackModerationStatus }) =>
      updateAdminFeedback(id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'feedback'] }),
  });
}

export function useRetriageFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => retriageAdminFeedback(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'feedback'] }),
  });
}

// The money-mover: Accept → €1 credit (if eligible) + private-repo ticket.
export function useAcceptFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => acceptAdminFeedback(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'feedback'] }),
  });
}
