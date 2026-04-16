import { useState } from "react";

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
}

export function FridgeItemModal({ mode, initialValues, onOk, onCancel }: FridgeItemModalProps) {
  const [name, setName] = useState(initialValues.name);
  const [quantity, setQuantity] = useState(String(initialValues.quantity_grams));
  const [expiration, setExpiration] = useState(initialValues.expiration_date ?? "");
  const [needToUse, setNeedToUse] = useState(initialValues.need_to_use);
  const [error, setError] = useState("");
  const [quantityError, setQuantityError] = useState("");

  const handleOk = () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    const parsedQuantity = Number(quantity);
    if (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0) {
      setQuantityError("Enter a quantity greater than 0");
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
          width: "340px",
          boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
          border: "1px solid #e0e0e0",
        }}
      >
        <h3 style={{ margin: "0 0 1rem 0" }}>
          {mode === "add" ? "Add Ingredient" : "Edit Ingredient"}
        </h3>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            Name
            <input
              type="text"
              value={name}
              onChange={(e) => { setName(e.target.value); setError(""); }}
              placeholder="e.g. Chicken breast"
              autoFocus
            />
            {error && <span style={{ color: "red", fontSize: "0.85rem" }}>{error}</span>}
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            Quantity (g)
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
              <span style={{ color: "red", fontSize: "0.85rem" }}>{quantityError}</span>
            )}
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            Expiration date
            <input
              type="date"
              value={expiration}
              onChange={(e) => setExpiration(e.target.value)}
              style={{ width: "160px" }}
            />
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={needToUse}
              onChange={(e) => setNeedToUse(e.target.checked)}
            />
            Need to use
          </label>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
          <button onClick={onCancel}>Cancel</button>
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
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
