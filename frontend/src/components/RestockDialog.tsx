import { useState, type CSSProperties } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../contexts/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import {
  cachedShelf,
  ShelfChangedError,
  useFinishPlan,
  useHousehold,
  usePlanList,
  useUpdateFridge,
  type ShelfData,
} from "../hooks/useServerState";
import { useI18n } from "../i18n";
import { localeTags } from "../i18n/localeFormat";
import type { StockItem } from "../types";
import { ModalShell } from "./ModalShell";
import { ReceiptScanner } from "./ReceiptScanner";

// An explicit dark surface, like the scanner it holds: legible in both schemes.
const SURFACE = "#0f172a";
const TEXT = "#e2e8f0";
const MUTED = "#94a3b8";
const ERROR = "#f87171";
const NOTICE: CSSProperties = { margin: "0 0 0.75rem", color: MUTED };

/**
 * Start fresh (docs/restock-design.md): scans become the new fridge list in
 * ONE version-checked PUT, carrying the token of the list it replaces. Every
 * entry point renders this only after the first fridge GET landed. Escape and
 * the backdrop do not close it: the rows are paid scans.
 */
export function RestockDialog({ onClose }: { onClose: () => void }) {
  const { t, tn, locale } = useI18n();
  const { userId, isDemo, householdsEnabled } = useAuth();
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();
  const read = (): ShelfData<StockItem> =>
    (userId === null ? undefined : cachedShelf<StockItem>(queryClient, "fridge", userId)) ?? {
      items: [],
      token: null,
    };
  // The list a save replaces and its token: what Undo puts back.
  const [snapshot, setSnapshot] = useState(read);
  const [done, setDone] = useState<ShelfData<StockItem> | null>(null);
  const [message, setMessage] = useState("");
  const { data: household } = useHousehold(userId, householdsEnabled && !isDemo);
  const { data: plans } = usePlanList(userId);
  const finishPlan = useFinishPlan();
  const updateFridge = useUpdateFridge();

  // Awaited, unlike useUpdateShelf's own reload after a 409: the next Save
  // must carry the token of the list as it is now, not the refused one.
  const recapture = async () => {
    await Promise.all([
      queryClient.refetchQueries({ queryKey: ["fridge", userId], exact: true }),
      queryClient.refetchQueries({ queryKey: ["planList", userId] }),
    ]);
    setSnapshot(read());
  };

  const save = async (items: StockItem[], generationIds: number[]) => {
    // Never an unchecked PUT: without a token the scanner is not even shown.
    if (userId === null || snapshot.token === null) return;
    setMessage("");
    try {
      const saved = await updateFridge.mutateAsync({ userId, items, token: snapshot.token, generationIds });
      void queryClient.invalidateQueries({ queryKey: ["restock", userId] });
      setDone(saved);
    } catch (err) {
      if (err instanceof ShelfChangedError) {
        await recapture();
        throw new Error(`${err.message} ${t("restock.saveAgain")}`);
      }
      throw new Error(t("fridge.saveFailed", { message: err instanceof Error ? err.message : "" }));
    }
  };

  const undo = async () => {
    if (userId === null || !done || done.token === null) return;
    setMessage("");
    try {
      // New rows: the snapshot's ids were deleted by the save.
      const items = snapshot.items.map((item) => ({ ...item, id: undefined }));
      await updateFridge.mutateAsync({ userId, items, token: done.token });
      onClose();
    } catch (err) {
      setMessage(
        err instanceof ShelfChangedError
          ? t("restock.undoRefused")
          : t("fridge.saveFailed", { message: err instanceof Error ? err.message : "" }),
      );
    }
  };

  const finish = async (planId: number) => {
    setMessage("");
    try {
      await finishPlan.mutateAsync(planId);
    } catch {
      setMessage(t("restock.finishFailed"));
    }
    // The finish put food back, or someone else's did: either way, read again.
    await recapture();
  };

  const openPlans = (plans ?? []).filter((p) => p.status === "planned" || p.status === "active");
  const shared = (household?.members.length ?? 0) > 1;
  const count = snapshot.items.length;

  return (
    <ModalShell onClose={() => {}} ariaLabel={t("restock.title")} closeOnEscape={false}>
      <div
        style={{
          background: SURFACE,
          color: TEXT,
          padding: "1.25rem",
          boxSizing: "border-box",
          overflowY: "auto",
          ...(isMobile
            ? { width: "100%", height: "100%" }
            : { width: "min(92vw, 760px)", maxHeight: "90vh", borderRadius: 12 }),
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
          <h2 style={{ margin: "0 0 0.75rem", fontSize: "1.3rem" }}>{t("restock.title")}</h2>
          {!done && <button onClick={onClose}>{t("restock.close")}</button>}
        </div>
        {done ? (
          <>
            <p style={{ margin: "0 0 1rem" }}>{tn("restock.done", done.items.length)}</p>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              {done.token !== null && (
                <button onClick={() => void undo()} disabled={updateFridge.isPending}>
                  {t("restock.undo")}
                </button>
              )}
              <button onClick={onClose}>{t("restock.close")}</button>
            </div>
          </>
        ) : (
          <>
            {count > 0 && <p style={NOTICE}>{tn("restock.replaces", count)}</p>}
            {shared && <p style={NOTICE}>{t("restock.shared")}</p>}
            {openPlans.map((plan) => (
              <div key={plan.id} style={{ display: "flex", gap: "0.75rem", alignItems: "center", margin: "0 0 0.75rem" }}>
                <p style={{ margin: 0, color: MUTED, flex: 1 }}>
                  {t("restock.openPlan", {
                    date: new Date(plan.created_at).toLocaleDateString(localeTags(locale), {
                      day: "numeric",
                      month: "short",
                    }),
                  })}
                </p>
                <button onClick={() => void finish(plan.id)} disabled={finishPlan.isPending}>
                  {t("restock.finishPlan")}
                </button>
              </div>
            ))}
            {snapshot.token === null ? (
              <p>{t("fridge.loading")}</p>
            ) : (
              <ReceiptScanner
                currentFridge={[]}
                onSave={save}
                saveLabel={(n) => tn("restock.save", n)}
              />
            )}
          </>
        )}
        {message && <p role="alert" style={{ color: ERROR, margin: "0.75rem 0 0" }}>{message}</p>}
      </div>
    </ModalShell>
  );
}
