import { useState, useRef } from "react";
import { useScanReceipt, useMergeFridge } from "../hooks/useServerState";
import type { ScannedItemType, StockItem } from "../types";

type ScannerState = "idle" | "scanning" | "review" | "error";

interface ReceiptScannerProps {
  currentFridge: StockItem[];
}

interface ReviewItem {
  name: string;
  addedQty: number;
  existingQty: number;
  needToUse: boolean;
  itemType?: ScannedItemType;
  expirationDate: string | null;
}

export function ReceiptScanner({ currentFridge }: ReceiptScannerProps) {
  const [state, setState] = useState<ScannerState>("idle");
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [notice, setNotice] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scanMutation = useScanReceipt();
  const mergeMutation = useMergeFridge();

  const handleScan = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    setState("scanning");
    setErrorMessage("");

    try {
      const scannedItems = await scanMutation.mutateAsync(file);

      // Build lookup from current fridge by (name, expiration_date) compound key
      const fridgeLookup = new Map<string, StockItem>();
      for (const item of currentFridge) {
        const compoundKey = `${item.name.trim().toLowerCase()}|${item.expiration_date ?? ""}`;
        fridgeLookup.set(compoundKey, item);
      }

      // Build review items with delta info
      const items: ReviewItem[] = scannedItems.map((scanned) => {
        const expDate = scanned.expiration_date ?? null;
        const compoundKey = `${scanned.name.trim().toLowerCase()}|${expDate ?? ""}`;
        const existing = fridgeLookup.get(compoundKey);
        return {
          name: scanned.name,
          addedQty: scanned.quantity_grams,
          existingQty: existing?.quantity_grams ?? 0,
          needToUse: existing?.need_to_use ?? false,
          itemType: scanned.item_type,
          expirationDate: expDate,
        };
      });

      setReviewItems(items);
      setState("review");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to scan receipt.");
      setState("error");
    }
  };

  const handleConfirm = async () => {
    const itemsToMerge: StockItem[] = reviewItems.map((item) => ({
      name: item.name,
      quantity_grams: item.addedQty,
      need_to_use: item.needToUse,
      expiration_date: item.expirationDate,
    }));

    try {
      await mergeMutation.mutateAsync(itemsToMerge);
      setState("idle");
      setReviewItems([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setNotice("Items added to fridge!");
      setTimeout(() => setNotice(""), 3000);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to merge items.");
      setState("error");
    }
  };

  const handleCancel = () => {
    setState("idle");
    setReviewItems([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const updateReviewItem = <K extends keyof ReviewItem>(
    index: number,
    field: K,
    value: ReviewItem[K],
  ) => {
    const updated = [...reviewItems];
    updated[index] = { ...updated[index], [field]: value };
    setReviewItems(updated);
  };

  const removeReviewItem = (index: number) => {
    const updated = [...reviewItems];
    updated.splice(index, 1);
    setReviewItems(updated);
  };

  return (
    <div style={{ marginBottom: "1.5rem", padding: "1rem", backgroundColor: "#1e293b", borderRadius: "8px", color: "rgba(255, 255, 255, 0.87)" }}>
      <h3 style={{ marginTop: 0 }}>Scan Receipt</h3>

      {/* File input — always visible in idle/error states */}
      {(state === "idle" || state === "error") && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,application/pdf,.pdf"
            aria-label="Select receipt image or PDF"
          />
          <button onClick={handleScan} disabled={scanMutation.isPending}>
            Scan Receipt
          </button>
        </div>
      )}

      {/* Scanning state */}
      {state === "scanning" && (
        <p>Scanning receipt... This may take a few seconds.</p>
      )}

      {/* Error state */}
      {state === "error" && (
        <p style={{ color: "red", marginTop: "0.5rem" }}>{errorMessage}</p>
      )}

      {/* Review state */}
      {state === "review" && (
        <>
          <p style={{ color: "#94a3b8", marginBottom: "0.5rem" }}>
            Review the extracted items before adding to your fridge.
          </p>
          {reviewItems.length === 0 ? (
            <p>No food items found in receipt.</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "0.5rem" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
                  <th>Ingredient</th>
                  <th>Type</th>
                  <th>Added Qty (g)</th>
                  <th>Expires</th>
                  <th>Result</th>
                  <th>Need to use?</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {reviewItems.map((item, index) => {
                  const resultQty = item.existingQty + item.addedQty;
                  const isNew = item.existingQty === 0;
                  return (
                    <tr key={index} style={{ borderBottom: "1px solid #eee" }}>
                      <td>
                        <input
                          type="text"
                          value={item.name}
                          onChange={(e) => updateReviewItem(index, "name", e.target.value)}
                        />
                      </td>
                      <td>
                        <span style={{
                          fontSize: "0.75rem",
                          padding: "0.15rem 0.4rem",
                          borderRadius: "4px",
                          backgroundColor: item.itemType === "ingredient" ? "#1e3a2f" : "#3b1e2f",
                          color: item.itemType === "ingredient" ? "#4ade80" : "#f9a8d4",
                        }}>
                          {item.itemType === "ingredient" ? "ingredient" : "snack"}
                        </span>
                      </td>
                      <td>
                        <input
                          type="number"
                          value={item.addedQty}
                          onChange={(e) => updateReviewItem(index, "addedQty", parseInt(e.target.value) || 0)}
                          style={{ width: "80px" }}
                        />
                      </td>
                      <td>
                        <input
                          type="date"
                          value={item.expirationDate ?? ""}
                          onChange={(e) => updateReviewItem(index, "expirationDate", e.target.value || null)}
                          style={{ width: "130px" }}
                        />
                      </td>
                      <td style={{ color: isNew ? "#4ade80" : "inherit" }}>
                        {isNew
                          ? `${item.addedQty}g (new)`
                          : `+${item.addedQty} → ${resultQty}g`}
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={item.needToUse}
                          onChange={() => updateReviewItem(index, "needToUse", !item.needToUse)}
                        />
                      </td>
                      <td>
                        <button onClick={() => removeReviewItem(index)}>Remove</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              onClick={handleConfirm}
              disabled={mergeMutation.isPending || reviewItems.length === 0}
              style={{ backgroundColor: "#2563eb", color: "white", border: "none", padding: "0.5rem 1rem", borderRadius: "4px", cursor: "pointer" }}
            >
              {mergeMutation.isPending ? "Adding..." : "Add to Fridge"}
            </button>
            <button onClick={handleCancel}>Cancel</button>
          </div>
        </>
      )}

      {notice && (
        <div style={{ marginTop: "0.5rem", color: "green" }}>{notice}</div>
      )}
    </div>
  );
}
