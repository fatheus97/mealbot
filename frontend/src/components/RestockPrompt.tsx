import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useAnswerRestock, useRestockStatus } from "../hooks/useServerState";
import { useI18n } from "../i18n";
import { ConfirmDialog } from "./ConfirmDialog";

/**
 * Asks once when the household's fridge list has gone unchanged for 14 days
 * (docs/restock-design.md, "Return after an absence"). Either answer is posted,
 * which stamps the server. `asked` is what keeps it closed for the rest of the
 * session: a focus refetch can still say due when that POST failed or raced it.
 * Mounted for the whole MainLayout, so the flag lives as long as the login.
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
  const eligible = onboardingCompleted && !isDemo;
  const { data } = useRestockStatus(userId, eligible);
  const answer = useAnswerRestock();
  const [asked, setAsked] = useState(false);
  // Opening Start fresh any other way (the Fridge button) is an answer too:
  // asking "Start fresh?" right after someone closed it would nag. Set during
  // render, React's pattern for state that follows a prop.
  if (restockOpen && !asked) setAsked(true);

  // days_since_write is always set when due; without it there is no sentence.
  if (!eligible || !data?.due || data.days_since_write === null || restockOpen || asked) {
    return null;
  }

  const reply = (start: boolean) => {
    setAsked(true);
    // Fire and forget: the prompt is gone either way, and a failed answer only
    // means it may ask again in a later session.
    answer.mutate();
    if (start) onStartRestock();
  };

  return (
    <ConfirmDialog
      destructive={false}
      title={t("restock.promptTitle")}
      message={tn("restock.promptMessage", data.days_since_write)}
      confirmLabel={t("fridge.startFresh")}
      cancelLabel={t("restock.notNow")}
      onConfirm={() => reply(true)}
      onCancel={() => reply(false)}
    />
  );
}
