import { useState } from "react";
import { useI18n } from "../i18n";

export interface FridgeItemValues {
  name: string;
  quantity_grams: number;
  expiration_date: string | null;
  need_to_use: boolean;
}

interface FridgeItemModalProps {
  mode: "add" | "edit";
  initialValues: FridgeItemValues;
  onOk: (values: FridgeItemValues) => void;
  onCancel: () => void;
  // Mirrors User.need_to_use_enabled — hides the field entirely when the user
  // has turned the feature off, rather than showing a control with no visible
  // effect (fridge reads mask need_to_use to false while disabled). The
  // underlying value still round-trips unchanged so re-enabling restores it.
  needToUseEnabled?: boolean;
}

export function FridgeItemModal({ mode, initialValues, onOk, onCancel, needToUseEnabled = true }: FridgeItemModalProps) {
  const { t } = useI18n();
  const [name, setName] = useState(initialValues.name);
  const [quantity, setQuantity] = useState(String(initialValues.quantity_grams));
  const [expiration, setExpiration] = useState(initialValues.expiration_date ?? "");
  const [needToUse, setNeedToUse] = useState(initialValues.need_to_use);
  const [error, setError] = useState("");
  const [quantityError, setQuantityError] = useState("");

  const handleOk = () => {
    if (!name.trim()) {
      setError(t("fridgeItem.nameRequired"));
      return;
    }
    const parsedQuantity = Number(quantity);
    if (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0) {
      setQuantityError(t("fridgeItem.quantityPositive"));
      return;
    }
    onOk({
      name: name.trim(),
      quantity_grams: parsedQuantity,
      expiration_date: expiration || null,
      need_to_use: needToUse,
    });
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.3)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        style={{
          backgroundColor: "white",
          color: "#111",
          borderRadius: "10px",
          padding: "1.5rem",
          width: "min(340px, calc(100vw - 1.5rem))",
          boxSizing: "border-box",
          boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
          border: "1px solid #e0e0e0",
        }}
      >
        <h3 style={{ margin: "0 0 1rem 0" }}>
          {mode === "add" ? t("fridgeItem.addTitle") : t("fridgeItem.editTitle")}
        </h3>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {t("fridgeItem.name")}
            <input
              type="text"
              value={name}
              onChange={(e) => { setName(e.target.value); setError(""); }}
              placeholder={t("fridgeItem.namePlaceholder")}
              autoFocus
            />
            {error && <span style={{ color: "#b91c1c", fontSize: "0.85rem" }}>{error}</span>}
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {t("fridgeItem.quantity")}
            <input
              type="text"
              inputMode="decimal"
              value={quantity}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "" || /^\d*\.?\d*$/.test(v)) {
                  setQuantity(v);
                  setQuantityError("");
                }
              }}
              style={{ width: "100px" }}
            />
            {quantityError && (
              <span style={{ color: "#b91c1c", fontSize: "0.85rem" }}>{quantityError}</span>
            )}
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {t("fridgeItem.expiration")}
            <input
              type="date"
              value={expiration}
              onChange={(e) => setExpiration(e.target.value)}
              style={{ width: "160px" }}
            />
          </label>

          {needToUseEnabled && (
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <input
                type="checkbox"
                checked={needToUse}
                onChange={(e) => setNeedToUse(e.target.checked)}
              />
              {t("fridgeItem.needToUse")}
            </label>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
          <button onClick={onCancel}>{t("fridgeItem.cancel")}</button>
          <button
            onClick={handleOk}
            style={{
              backgroundColor: "#2563eb",
              color: "white",
              border: "none",
              borderRadius: "4px",
              padding: "0.4rem 1rem",
              cursor: "pointer",
            }}
          >
            {t("fridgeItem.ok")}
          </button>
        </div>
      </div>
    </div>
  );
}
