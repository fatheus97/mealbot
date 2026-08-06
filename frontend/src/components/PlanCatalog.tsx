import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import { usePlanList, useDeletePlan, useReschedulePlan } from "../hooks/useServerState";
import { fetchPlan } from "../api";
import { ConfirmDialog } from "./ConfirmDialog";
import type { MealPlanResponse, MealPlanSummary, PlanStatus } from "../types";
import { useI18n } from "../i18n";

const STATUS_COLORS: Record<PlanStatus, { bg: string; text: string }> = {
  planned: { bg: "#e2e8f0", text: "#475569" },
  active: { bg: "#dbeafe", text: "#1d4ed8" },
  cooked: { bg: "#dcfce7", text: "#166534" }, // 6.49:1 (was #16a34a, 3.00:1)
  finished: { bg: "#f3e8ff", text: "#7c3aed" },
};

interface PlanCatalogProps {
  onOpenPlan: (plan: MealPlanResponse, summary: MealPlanSummary) => void;
}

export function PlanCatalog({ onOpenPlan }: PlanCatalogProps) {
  const { t } = useI18n();
  const { userId } = useAuth();
  const isMobile = useIsMobile();
  const { data: plans, isLoading } = usePlanList(userId);
  const deleteMutation = useDeletePlan();
  const rescheduleMutation = useReschedulePlan();
  const [expanded, setExpanded] = useState(true);
  const [loadingPlanId, setLoadingPlanId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [rescheduleError, setRescheduleError] = useState<string | null>(null);
  // Bumped on a failed reschedule to remount the (uncontrolled) date inputs
  // back onto the server value.
  const [rescheduleNonce, setRescheduleNonce] = useState(0);

  if (!userId) return null;

  const handleOpen = async (summary: MealPlanSummary) => {
    setLoadingPlanId(summary.id);
    setOpenError(null);
    try {
      const data: MealPlanResponse = await fetchPlan(summary.id);
      onOpenPlan(data, summary);
    } catch (err) {
      console.error(t("plans.loadFailedPrefix"), err);
      setOpenError(t("plans.openFailed"));
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
        : t("plans.deleteFailed")
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
        <h2 style={{ margin: 0 }}>{t("plans.title")}</h2>
        {plans && plans.length > 0 && (
          <span style={{ fontSize: "0.85rem", color: "#888" }}>({plans.length})</span>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: "1rem" }}>
          {isLoading && <p style={{ color: "#888" }}>{t("plans.loading")}</p>}

          {openError && (
            <p role="alert" style={{ color: "#b91c1c", fontSize: "0.9rem", marginTop: 0 }}>
              {openError}
            </p>
          )}
          {rescheduleError && (
            <p role="alert" style={{ color: "#b91c1c", fontSize: "0.9rem", marginTop: 0 }}>
              {rescheduleError}
            </p>
          )}

          {plans && plans.length === 0 && (
            <p style={{ color: "#888", fontSize: "0.9rem" }}>
              {t("plans.empty")}
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
                      // Mobile: stack the info over the actions (a single row is
                      // too wide for a phone and the Delete button gets clipped).
                      flexDirection: isMobile ? "column" : "row",
                      alignItems: isMobile ? "stretch" : "center",
                      justifyContent: "space-between",
                      gap: isMobile ? "0.6rem" : undefined,
                      padding: "0.75rem 1rem",
                      backgroundColor: "#f9f9f9",
                      border: "1px solid #e5e7eb",
                      borderRadius: "6px",
                      fontSize: "0.9rem",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: isMobile ? "0.5rem 1rem" : "1rem", flexWrap: "wrap", flex: 1 }}>
                      <span style={{ color: "#555", minWidth: "90px" }}>
                        {formatDate(plan.created_at)}
                      </span>
                      {/* Explicit dark color: the card bg is a fixed light
                          (#f9f9f9), so inheriting the scheme's text color would
                          render white-on-light in dark mode. */}
                      <span style={{ color: "#333" }}>
                        {t("plans.summary", {
                          days: plan.days,
                          meals: plan.meals_per_day,
                          people: plan.people_count,
                        })}
                      </span>
                      {/* Editable schedule date — reschedule (or clear) any plan
                          right here, not only inside the calendar. Uncontrolled
                          (key + defaultValue) so a successful move remounts on the
                          new server date without snap-back; a failed one resets via
                          the nonce bump. A date input is already YYYY-MM-DD, so no
                          UTC-shifting `new Date(str)` is involved. */}
                      <label style={{ color: "#555", display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "0.85rem" }}>
                        <span aria-hidden>📅</span>
                        <input
                          key={`${plan.start_date}-${rescheduleNonce}`}
                          type="date"
                          aria-label={`Reschedule plan ${plan.id}`}
                          defaultValue={plan.start_date ?? ""}
                          onChange={(e) =>
                            rescheduleMutation.mutate(
                              { planId: plan.id, startDate: e.target.value || null },
                              {
                                onSuccess: () => setRescheduleError(null),
                                onError: () => {
                                  setRescheduleError(
                                    t("plans.dateFailed"),
                                  );
                                  setRescheduleNonce((n) => n + 1);
                                },
                              },
                            )
                          }
                          style={{ padding: "0.15rem 0.3rem", fontSize: "0.8rem" }}
                        />
                      </label>
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
                        {t("plans.statusCount", {
                          status: t(`planStatus.${plan.status}` as const),
                          cooked: plan.cooked_meals,
                          total: plan.total_meals,
                        })}
                      </span>
                    </div>

                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button
                        onClick={() => handleOpen(plan)}
                        disabled={loadingPlanId === plan.id}
                        style={{
                          flex: isMobile ? 1 : undefined,
                          padding: "0.3rem 0.8rem",
                          fontSize: "0.85rem",
                          backgroundColor: "#4a90d9",
                          color: "#fff",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                        }}
                      >
                        {loadingPlanId === plan.id ? t("plans.opening") : t("plans.open")}
                      </button>

                      <button
                        onClick={() => setConfirmDeleteId(plan.id)}
                        style={{
                          flex: isMobile ? 1 : undefined,
                          padding: "0.3rem 0.8rem",
                          fontSize: "0.85rem",
                          backgroundColor: "#fee2e2",
                          color: "#dc2626",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                        }}
                      >
                        {t("plans.delete")}
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
          title={t("plans.deleteTitle")}
          message={`This will permanently delete the ${planPendingDelete.days}-day / ${planPendingDelete.meals_per_day}-meal plan from ${formatDate(planPendingDelete.created_at)}. This cannot be undone.`}
          confirmLabel={t("plans.delete")}
          loadingLabel={t("plans.deleting")}
          loading={deleteMutation.isPending}
          error={deleteError}
          onConfirm={() => handleDelete(planPendingDelete.id)}
          onCancel={cancelDelete}
        />
      )}
    </section>
  );
}
