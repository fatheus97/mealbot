import { useRef, useState, type CSSProperties } from "react";
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

/** A list as the server compares it: a (name, quantity, expiry) multiset, no ids. */
const listKey = (items: StockItem[]) =>
  items
    .map((i) => JSON.stringify([i.name, i.quantity_grams, i.expiration_date ?? null]))
    .sort()
    .join(",");

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
  const [undoRefused, setUndoRefused] = useState(false);
  const [message, setMessage] = useState("");
  // A save, Empty, Undo or Finish it in flight: everything else waits, Close
  // included (closing mid-save would land the replace with no Undo).
  const [busy, setBusy] = useState(false);
  // What the last Save sent, to recognise it on the server after a lost reply.
  const lastSent = useRef<StockItem[] | null>(null);
  const { data: household } = useHousehold(userId, householdsEnabled && !isDemo);
  const { data: plans } = usePlanList(userId);
  const finishPlan = useFinishPlan();
  const updateFridge = useUpdateFridge();

  // Awaited, unlike useUpdateShelf's own reload after a 409: the next Save
  // must carry the token of the list as it is now, not the refused one.
  // Returns the fresh list when it is exactly what the last Save sent: that
  // Save landed and only its reply was lost.
  // Throws when the reload fails or brings no token: the snapshot then stays
  // as it was (a null token would unmount the scanner and its paid rows).
  const recapture = async (): Promise<ShelfData<StockItem> | null> => {
    await Promise.all([
      queryClient.refetchQueries({ queryKey: ["fridge", userId], exact: true }, { throwOnError: true }),
      queryClient.refetchQueries({ queryKey: ["planList", userId] }, { throwOnError: true }),
    ]);
    const fresh = read();
    if (fresh.token === null) throw new Error("fridge reload carried no version token");
    const sent = lastSent.current;
    const ownSaveLanded = sent !== null && listKey(fresh.items) === listKey(sent);
    // Keep the list that save replaced, so Undo still puts THAT back, and take
    // just the new token; otherwise someone else wrote, so take their list.
    setSnapshot((prev) => (ownSaveLanded ? { items: prev.items, token: fresh.token } : fresh));
    return ownSaveLanded ? fresh : null;
  };

  const holding = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
    } finally {
      setBusy(false);
    }
  };

  const save = (items: StockItem[], generationIds: number[]) =>
    holding(async () => {
      // Never an unchecked PUT. Unreachable (no token, no scanner), but if it
      // ever is, fail loudly: a silent return would read as saved and the
      // scanner would clear its paid rows.
      if (userId === null || snapshot.token === null) throw new Error(t("restock.saveFailed"));
      setMessage("");
      lastSent.current = items;
      try {
        const saved = await updateFridge.mutateAsync({ userId, items, token: snapshot.token, generationIds });
        void queryClient.invalidateQueries({ queryKey: ["restock", userId] });
        setDone(saved);
      } catch (err) {
        if (err instanceof ShelfChangedError) {
          let landed: ShelfData<StockItem> | null;
          try {
            landed = await recapture();
          } catch {
            // Could not see what changed: say so, not "someone changed it".
            throw new Error(t("restock.saveFailed"));
          }
          // Not a partner's change: our earlier Save is on the server, so this
          // restock is done (blaming "someone" here would be wrong).
          if (landed) {
            void queryClient.invalidateQueries({ queryKey: ["restock", userId] });
            setDone(landed);
            return;
          }
          throw new Error(t("restock.changedMeanwhile"));
        }
        throw new Error(t("restock.saveFailed"));
      }
    });

  const undo = () =>
    holding(async () => {
      if (userId === null || !done || done.token === null) return;
      setMessage("");
      try {
        // New rows: the snapshot's ids were deleted by the save.
        const items = snapshot.items.map((item) => ({ ...item, id: undefined }));
        await updateFridge.mutateAsync({ userId, items, token: done.token });
        onClose();
      } catch (err) {
        const refused = err instanceof ShelfChangedError;
        // Refused for good: the count and Undo would both be stale.
        setUndoRefused(refused);
        setMessage(refused ? t("restock.undoRefused") : t("restock.undoFailed"));
      }
    });

  const finish = (planId: number) =>
    holding(async () => {
      setMessage("");
      try {
        await finishPlan.mutateAsync(planId);
      } catch {
        setMessage(t("restock.finishFailed"));
      }
      // The finish put food back, or someone else's did: either way, read again.
      // A failed reload keeps the old token, and the next Save's 409 reloads.
      await recapture().catch(() => undefined);
    });

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
          {/* One Close for both screens. It takes the focus on open, because
              Escape and the backdrop are off. */}
          <button onClick={onClose} disabled={busy} autoFocus>
            {t("restock.close")}
          </button>
        </div>
        {done ? (
          !undoRefused && (
            <>
              <p style={{ margin: "0 0 1rem" }}>{tn("restock.done", done.items.length)}</p>
              {done.token !== null && (
                <button onClick={() => void undo()} disabled={busy}>
                  {t("restock.undo")}
                </button>
              )}
            </>
          )
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
                <button onClick={() => void finish(plan.id)} disabled={busy}>
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
                disabled={busy}
              />
            )}
          </>
        )}
        {message && <p role="alert" style={{ color: ERROR, margin: "0.75rem 0 0" }}>{message}</p>}
      </div>
    </ModalShell>
  );
}
