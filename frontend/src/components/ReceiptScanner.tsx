import { useState, useRef } from "react";
import type { ChangeEvent } from "react";
import { useScanReceipt, useMergeFridge } from "../hooks/useServerState";
import { useAuth } from "../contexts/AuthContext";
import type { ScannedItemType, StockItem } from "../types";
import demoReceiptUrl from "../assets/demo-receipt.svg";

type ScannerState = "idle" | "scanning" | "review" | "error";

interface ReceiptScannerProps {
  currentFridge: StockItem[];
}

interface ReviewItem {
  name: string;
  addedQty: string;
  existingQty: number;
  needToUse: boolean;
  itemType?: ScannedItemType;
  expirationDate: string | null;
}

const parseQty = (s: string): number => {
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : NaN;
};

// Expiration dates are computed from shelf-life days at click time so the
// demo always shows dates relative to today — no stale "expired yesterday"
// rows for recruiters who open the demo weeks after the build.
const DEMO_SCAN_TEMPLATE: Array<Omit<ReviewItem, "expirationDate"> & { shelfLifeDays: number }> = [
  { name: "Whole Milk",        addedQty: "1000", existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 7 },
  { name: "Eggs",              addedQty: "360",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 21 },
  { name: "Bananas",           addedQty: "300",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 5 },
  { name: "Butter",            addedQty: "250",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 30 },
  { name: "Roma Tomatoes",     addedQty: "500",  existingQty: 0, needToUse: true,  itemType: "ingredient", shelfLifeDays: 4 },
  { name: "Whole Wheat Bread", addedQty: "500",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 7 },
];

const buildDemoScanItems = (): ReviewItem[] => {
  const today = new Date();
  return DEMO_SCAN_TEMPLATE.map(({ shelfLifeDays, ...item }) => {
    const exp = new Date(today);
    exp.setDate(exp.getDate() + shelfLifeDays);
    // YYYY-MM-DD in local time — matches the <input type="date"> format and
    // the backend's ISO date representation.
    const y = exp.getFullYear();
    const m = String(exp.getMonth() + 1).padStart(2, "0");
    const d = String(exp.getDate()).padStart(2, "0");
    return { ...item, expirationDate: `${y}-${m}-${d}` };
  });
};

export function ReceiptScanner({ currentFridge }: ReceiptScannerProps) {
  const { isDemo } = useAuth();
  const [state, setState] = useState<ScannerState>("idle");
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [notice, setNotice] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scanMutation = useScanReceipt();
  const mergeMutation = useMergeFridge();

  const handleScan = async (file: File) => {
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
          addedQty: String(scanned.quantity_grams),
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
    } finally {
      // Reset so selecting the same file again (e.g. after an error) re-triggers onChange.
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDemoScan = () => {
    setState("scanning");
    setTimeout(() => {
      setReviewItems(buildDemoScanItems());
      setState("review");
    }, 1200);
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    void handleScan(file);
  };

  const handleConfirm = async () => {
    const invalidIdx = reviewItems.findIndex((item) => Number.isNaN(parseQty(item.addedQty)));
    if (invalidIdx !== -1) {
      setConfirmError(
        `Row ${invalidIdx + 1} (${reviewItems[invalidIdx].name || "unnamed"}) needs a quantity greater than 0.`,
      );
      return;
    }

    const itemsToMerge: StockItem[] = reviewItems.map((item) => ({
      name: item.name,
      quantity_grams: parseQty(item.addedQty),
      need_to_use: item.needToUse,
      expiration_date: item.expirationDate,
    }));

    try {
      await mergeMutation.mutateAsync(itemsToMerge);
      setState("idle");
      setReviewItems([]);
      setConfirmError("");
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
    setConfirmError("");
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

      {/* File input — always visible in idle/error states. Selecting a file auto-triggers the scan. */}
      {(state === "idle" || state === "error") && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
          {isDemo ? (
            <>
              <img
                src={demoReceiptUrl}
                alt="Demo grocery receipt"
                style={{ height: 120, border: "1px solid #334155", borderRadius: 4 }}
              />
              <button onClick={handleDemoScan} disabled={scanMutation.isPending}>
                Scan demo receipt
              </button>
            </>
          ) : (
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,application/pdf,.pdf"
              aria-label="Select receipt image or PDF"
              onChange={handleFileChange}
              disabled={scanMutation.isPending}
            />
          )}
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
                  const addedNum = parseQty(item.addedQty);
                  const isInvalid = Number.isNaN(addedNum);
                  const isNew = item.existingQty === 0;
                  const resultLabel = isInvalid
                    ? "—"
                    : isNew
                      ? `${addedNum}g (new)`
                      : `+${addedNum} → ${item.existingQty + addedNum}g`;
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
                          type="text"
                          inputMode="decimal"
                          value={item.addedQty}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === "" || /^\d*\.?\d*$/.test(v)) {
                              updateReviewItem(index, "addedQty", v);
                              setConfirmError("");
                            }
                          }}
                          style={{
                            width: "80px",
                            border: isInvalid ? "1px solid #ef4444" : undefined,
                          }}
                          aria-invalid={isInvalid}
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
                      <td style={{ color: isNew && !isInvalid ? "#4ade80" : "inherit" }}>
                        {resultLabel}
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
          {confirmError && (
            <p style={{ color: "#f87171", margin: "0.25rem 0 0.5rem" }}>{confirmError}</p>
          )}
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
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
