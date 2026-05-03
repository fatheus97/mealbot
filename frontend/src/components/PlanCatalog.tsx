import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { usePlanList, useDeletePlan } from "../hooks/useServerState";
import { fetchPlan } from "../api";
import { ConfirmDialog } from "./ConfirmDialog";
import type { MealPlanResponse, MealPlanSummary, PlanStatus } from "../types";

const STATUS_COLORS: Record<PlanStatus, { bg: string; text: string }> = {
  planned: { bg: "#e2e8f0", text: "#475569" },
  active: { bg: "#dbeafe", text: "#1d4ed8" },
  cooked: { bg: "#dcfce7", text: "#16a34a" },
  finished: { bg: "#f3e8ff", text: "#7c3aed" },
};

interface PlanCatalogProps {
  onOpenPlan: (plan: MealPlanResponse, summary: MealPlanSummary) => void;
}

export function PlanCatalog({ onOpenPlan }: PlanCatalogProps) {
  const { userId } = useAuth();
  const { data: plans, isLoading } = usePlanList(userId);
  const deleteMutation = useDeletePlan();
  const [expanded, setExpanded] = useState(true);
  const [loadingPlanId, setLoadingPlanId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  if (!userId) return null;

  const handleOpen = async (summary: MealPlanSummary) => {
    setLoadingPlanId(summary.id);
    setOpenError(null);
    try {
      const data: MealPlanResponse = await fetchPlan(summary.id);
      onOpenPlan(data, summary);
    } catch (err) {
      console.error("Failed to load plan:", err);
      setOpenError("Couldn't open that plan. Please try again.");
    } finally {
      setLoadingPlanId(null);
    }
  };

  const handleDelete = (planId: number) => {
    deleteMutation.mutate(planId, {
      onSuccess: () => setConfirmDeleteId(null),
    });
  };

  const cancelDelete = () => {
    if (deleteMutation.isPending) return;
    setConfirmDeleteId(null);
    // Clear any prior error so a future open doesn't render stale state.
    deleteMutation.reset();
  };

  const planPendingDelete = plans?.find((p) => p.id === confirmDeleteId) ?? null;
  const deleteError =
    deleteMutation.isError && deleteMutation.variables === confirmDeleteId
      ? deleteMutation.error instanceof Error
        ? deleteMutation.error.message
        : "Failed to delete plan."
      : null;

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  return (
    <section style={{ marginBottom: "2rem", borderTop: "2px solid #eee", paddingTop: "1.5rem" }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", userSelect: "none" }}
        onClick={() => setExpanded(!expanded)}
      >
        <span style={{ fontSize: "0.9rem", color: "#888" }}>{expanded ? "\u25BC" : "\u25B6"}</span>
        <h2 style={{ margin: 0 }}>My Plans</h2>
        {plans && plans.length > 0 && (
          <span style={{ fontSize: "0.85rem", color: "#888" }}>({plans.length})</span>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: "1rem" }}>
          {isLoading && <p style={{ color: "#888" }}>Loading plans...</p>}

          {openError && (
            <p role="alert" style={{ color: "#b91c1c", fontSize: "0.9rem", marginTop: 0 }}>
              {openError}
            </p>
          )}

          {plans && plans.length === 0 && (
            <p style={{ color: "#888", fontSize: "0.9rem" }}>
              No plans yet. Generate one below to get started.
            </p>
          )}

          {plans && plans.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {plans.map((plan: MealPlanSummary) => {
                const colors = STATUS_COLORS[plan.status];
                return (
                  <div
                    key={plan.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "0.75rem 1rem",
                      backgroundColor: "#f9f9f9",
                      border: "1px solid #e5e7eb",
                      borderRadius: "6px",
                      fontSize: "0.9rem",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "1rem", flex: 1 }}>
                      <span style={{ color: "#555", minWidth: "90px" }}>
                        {formatDate(plan.created_at)}
                      </span>
                      <span>
                        {plan.days}d / {plan.meals_per_day} meals / {plan.people_count}p
                      </span>
                      <span
                        style={{
                          padding: "0.15rem 0.5rem",
                          borderRadius: "12px",
                          fontSize: "0.8rem",
                          fontWeight: 600,
                          backgroundColor: colors.bg,
                          color: colors.text,
                        }}
                      >
                        {plan.status} ({plan.cooked_meals}/{plan.total_meals})
                      </span>
                    </div>

                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button
                        onClick={() => handleOpen(plan)}
                        disabled={loadingPlanId === plan.id}
                        style={{
                          padding: "0.3rem 0.8rem",
                          fontSize: "0.85rem",
                          backgroundColor: "#4a90d9",
                          color: "#fff",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                        }}
                      >
                        {loadingPlanId === plan.id ? "Loading..." : "Open"}
                      </button>

                      <button
                        onClick={() => setConfirmDeleteId(plan.id)}
                        style={{
                          padding: "0.3rem 0.8rem",
                          fontSize: "0.85rem",
                          backgroundColor: "#fee2e2",
                          color: "#dc2626",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {planPendingDelete && (
        <ConfirmDialog
          title="Delete this plan?"
          message={`This will permanently delete the ${planPendingDelete.days}-day / ${planPendingDelete.meals_per_day}-meal plan from ${formatDate(planPendingDelete.created_at)}. This cannot be undone.`}
          confirmLabel="Delete"
          loadingLabel="Deleting…"
          loading={deleteMutation.isPending}
          error={deleteError}
          onConfirm={() => handleDelete(planPendingDelete.id)}
          onCancel={cancelDelete}
        />
      )}
    </section>
  );
}
