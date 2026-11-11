import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../contexts/AuthContext";
import { cachedShelf, useAnswerRestock, useFridge, useRestockStatus } from "../hooks/useServerState";
import { useI18n } from "../i18n";
import { ConfirmDialog } from "./ConfirmDialog";

/**
 * Asks once when the household's fridge list has gone unchanged for 14 days
 * (docs/restock-design.md, "Return after an absence"). Not now posts the
 * answer; so does opening Start fresh by any route while it is due, this
 * prompt's button included. `asked` keeps it closed while this is mounted,
 * because a focus refetch can still say due when that POST failed or raced
 * it. MainLayout remounts it on login and after an admin's Admin view, which
 * drops the flag: by then a landed answer has the server saying not due, and
 * only a failed one can ask again.
 */
export function RestockPrompt({
  restockOpen,
  onStartRestock,
}: {
  restockOpen: boolean;
  onStartRestock: () => void;
}) {
  const { userId, onboardingCompleted, isDemo } = useAuth();
  const { t, tn } = useI18n();
  const queryClient = useQueryClient();
  const eligible = onboardingCompleted && !isDemo;
  const { data } = useRestockStatus(userId, eligible);
  const due = data?.due === true;
  // RestockDialog reads the fridge and its token once, at mount: without them
  // it would sit on its loading copy. The Fridge button waits the same way.
  const { data: fridge } = useFridge(userId);
  const fridgeReady =
    fridge !== undefined && userId !== null && cachedShelf(queryClient, "fridge", userId)?.token != null;
  const { mutate: answer } = useAnswerRestock();
  const [asked, setAsked] = useState(false);
  // Opening Start fresh any other way (the Fridge button) is an answer too:
  // asking "Start fresh?" right after someone closed it would nag. Set during
  // render, React's pattern for state that follows a prop.
  if (restockOpen && !asked) setAsked(true);

  // Fire and forget, like Not now: a failed answer only means it may ask
  // again after a remount.
  useEffect(() => {
    if (restockOpen && eligible && due) answer();
  }, [restockOpen, eligible, due, answer]);

  // days_since_write is always set when due; without it there is no sentence.
  // An open restock dialog hides it through `asked`, set above.
  if (!eligible || !due || data?.days_since_write == null || !fridgeReady || asked) {
    return null;
  }

  return (
    <ConfirmDialog
      destructive={false}
      title={t("restock.promptTitle")}
      message={tn("restock.promptMessage", data.days_since_write)}
      confirmLabel={t("fridge.startFresh")}
      cancelLabel={t("restock.notNow")}
      // Opening the dialog answers (the effect above).
      onConfirm={onStartRestock}
      onCancel={() => {
        setAsked(true);
        answer();
      }}
    />
  );
}
