import { useState } from "react";
import type { StockItem } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";
import { useI18n } from "../i18n";
import { formatISODate } from "../utils/planDates";

export type ExpiredChoice = "thrown_out" | "still_fine";

export interface ExpiredDecision {
  item: StockItem;
  choice: ExpiredChoice;
}

interface ExpiredReviewDialogProps {
  /** Already filtered to items past their expiry date, in display order. */
  items: StockItem[];
  onApply: (decisions: ExpiredDecision[]) => void;
  onSkip: () => void;
  applying?: boolean;
}

/**
 * Shown after a plan is finished, when the fridge holds items past their date.
 *
 * The list is machine-derived and every row starts unanswered, so the whole
 * dialog can be dismissed with one click. That is deliberate: this exists to
 * clean up the fridge and to correct expiry dates the receipt scanner guessed
 * wrong. Capturing waste is a by-product of a job the user already wanted done,
 * not a chore performed on the app's behalf.
 */
export function ExpiredReviewDialog({
  items,
  onApply,
  onSkip,
  applying = false,
}: ExpiredReviewDialogProps) {
  const { t, tn, locale } = useI18n();
  // Keyed by index into `items`, which is fixed for this dialog's lifetime —
  // the parent snapshots the expired list before opening it.
  const [choices, setChoices] = useState<Record<number, ExpiredChoice>>({});

  const handleConfirm = () => {
    onApply(
      items
        .map((item, i) => ({ item, choice: choices[i] }))
        .filter((d): d is ExpiredDecision => d.choice !== undefined),
    );
  };

  return (
    <ConfirmDialog
      title={t("expired.title")}
      message={tn("expired.body", items.length)}
      confirmLabel={t("expired.apply")}
      cancelLabel={t("expired.skip")}
      loadingLabel={t("expired.applying")}
      loading={applying}
      destructive={false}
      onConfirm={handleConfirm}
      onCancel={onSkip}
    >
      {/* Scrolls on its own: ConfirmDialog's panel has no max-height, so a
          long list would otherwise push the buttons off-screen. */}
      <div style={{ maxHeight: "42vh", overflowY: "auto", margin: "0 0 1rem 0" }}>
        {items.map((item, i) => (
          <fieldset
            key={item.id ?? `${item.name}-${item.expiration_date}-${i}`}
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: "6px",
              padding: "0.5rem 0.7rem",
              margin: "0 0 0.5rem 0",
            }}
          >
            {/* Inside ConfirmDialog's explicit white/#111 surface, so these
                foregrounds are measured against white in BOTH themes. */}
            <legend style={{ fontSize: "0.85rem", color: "#111", padding: "0 0.3rem" }}>
              {item.name}
            </legend>
            <p style={{ fontSize: "0.78rem", color: "#374151", margin: "0 0 0.4rem" }}>
              {t("expired.itemMeta", {
                grams: Math.round(item.quantity_grams),
                date: item.expiration_date
                  ? formatISODate(item.expiration_date, locale)
                  : "—",
              })}
            </p>
            <div style={{ display: "flex", gap: "0.9rem", flexWrap: "wrap" }}>
              {([
                ["still_fine", "expired.stillFine"],
                ["thrown_out", "expired.thrownOut"],
              ] as const).map(([value, labelKey]) => (
                <label
                  key={value}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.35rem",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                    color: "#111",
                  }}
                >
                  <input
                    type="radio"
                    // Per-row group: sharing one name across rows would make the
                    // whole list a single choice.
                    name={`expired-${i}`}
                    value={value}
                    checked={choices[i] === value}
                    onChange={() => setChoices((prev) => ({ ...prev, [i]: value }))}
                  />
                  {t(labelKey)}
                </label>
              ))}
            </div>
          </fieldset>
        ))}
      </div>
      <p style={{ fontSize: "0.78rem", color: "#374151", margin: "0 0 1rem" }}>
        {t("expired.optionalHint")}
      </p>
    </ConfirmDialog>
  );
}
