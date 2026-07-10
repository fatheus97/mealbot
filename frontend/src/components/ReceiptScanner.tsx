import { useState, useRef, useEffect } from "react";
import type { ChangeEvent } from "react";
import { useScanReceipt, useMergeFridge } from "../hooks/useServerState";
import { useAuth } from "../contexts/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import type { ScannedItemType, StockItem } from "../types";
import demoReceiptUrl from "../assets/demo-receipt.svg";

type ScannerState = "idle" | "scanning" | "review" | "error" | "camera";

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
  const isMobile = useIsMobile();
  const [state, setState] = useState<ScannerState>("idle");
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  // machine_generation id for the scan on screen — echoed back on merge so the
  // server can capture edits made in the review table. null on the demo path
  // (no real /scan call) or when the scan telemetry write was skipped.
  const [scanGenerationId, setScanGenerationId] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [notice, setNotice] = useState("");
  // Camera is being acquired (permission prompt open) — disables the file input
  // and the button so a competing action can't race the in-flight getUserMedia.
  const [cameraOpening, setCameraOpening] = useState(false);
  // The preview <video> has metadata (a real frame), so Capture is safe to hit.
  const [videoReady, setVideoReady] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);
  // Guards against a second openCamera() (e.g. rapid double-tap of "Take photo")
  // racing the first — two getUserMedia calls would strand the first stream.
  const openingRef = useRef(false);
  // A ref mirror of `state` so the async openCamera() can read the CURRENT state
  // after its await (the closure's `state` is stale).
  const stateRef = useRef<ScannerState>(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const scanMutation = useScanReceipt();
  const mergeMutation = useMergeFridge();

  // getUserMedia needs a secure context (HTTPS or localhost) and the API present.
  // Evaluated at render (not module load) so it reflects the live environment.
  const cameraSupported =
    typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

  // Release the camera (stop every track) — call on capture, cancel, and unmount
  // so a live camera indicator never lingers after the user is done.
  const stopCamera = () => {
    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  // Attach the live stream once the <video> for the camera state has mounted.
  useEffect(() => {
    if (state === "camera" && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [state]);

  // Safety net: stop the camera if the component unmounts mid-capture, and track
  // mounted state so an in-flight openCamera() doesn't strand a stream (below).
  // The setup body MUST reset mountedRef to true: under StrictMode (dev) React
  // runs setup→cleanup→setup on mount, and without this the cleanup's `= false`
  // would stick, making openCamera always think it's unmounted.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const stream = streamRef.current;
      if (stream) stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  const openCamera = async () => {
    // Ignore re-entrant calls while a prompt/stream is already in flight or open.
    if (openingRef.current || streamRef.current) return;
    openingRef.current = true;
    setCameraOpening(true);
    setVideoReady(false);
    setErrorMessage("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      // If we're no longer in a state where the camera should open — unmounted,
      // or the user did something else during the (non-modal) permission prompt
      // that moved us into a busy state (scanning/review/camera) — stop this
      // just-acquired stream instead of clobbering that action and leaking the
      // camera. "idle" and "error" are both openable (the button shows in both,
      // so retry-after-denial must still work).
      const openableState =
        stateRef.current === "idle" || stateRef.current === "error";
      if (!mountedRef.current || !openableState) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      setState("camera");
    } catch (err) {
      // Permission denied / no camera / insecure context — degrade to file upload
      // (the idle/error state still renders the file input).
      const name = err instanceof DOMException ? err.name : "";
      setErrorMessage(
        name === "NotAllowedError"
          ? "Camera permission denied — you can upload a photo instead."
          : name === "NotFoundError"
            ? "No camera found — you can upload a photo instead."
            : "Couldn't open the camera — you can upload a photo instead.",
      );
      setState("error");
    } finally {
      openingRef.current = false;
      setCameraOpening(false);
    }
  };

  const capturePhoto = () => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      stopCamera();
      setErrorMessage("Couldn't capture the photo — try uploading instead.");
      setState("error");
      return;
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    // canvas → JPEG deliberately: gives us format control (sidesteps iOS HEIC,
    // which the backend rejects) AND compresses the phone photo before upload.
    canvas.toBlob(
      (blob) => {
        stopCamera();
        if (!blob) {
          setErrorMessage("Couldn't capture the photo — try uploading instead.");
          setState("error");
          return;
        }
        void handleScan(new File([blob], "receipt.jpg", { type: "image/jpeg" }));
      },
      "image/jpeg",
      0.85,
    );
  };

  const closeCamera = () => {
    stopCamera();
    setState("idle");
  };

  const handleScan = async (file: File) => {
    setState("scanning");
    setErrorMessage("");
    setScanGenerationId(null);

    try {
      const scanResponse = await scanMutation.mutateAsync(file);
      const scannedItems = scanResponse.items;
      setScanGenerationId(scanResponse.generation_id);

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
    setScanGenerationId(null); // demo skips the real /scan, so no generation
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
      await mergeMutation.mutateAsync({ items: itemsToMerge, generationId: scanGenerationId });
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
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,application/pdf,.pdf"
                aria-label="Select receipt image or PDF"
                onChange={handleFileChange}
                disabled={scanMutation.isPending || cameraOpening}
              />
              {cameraSupported && (
                <button onClick={openCamera} disabled={scanMutation.isPending || cameraOpening}>
                  {cameraOpening ? "Opening camera…" : "📷 Take photo"}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* Camera capture state — live preview + snap. Snapping draws the frame to
          a canvas → JPEG → the same handleScan() path as an uploaded file. */}
      {state === "camera" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            aria-label="Camera preview"
            onLoadedMetadata={() => setVideoReady(true)}
            style={{ width: "100%", maxWidth: 480, borderRadius: 8, background: "#000" }}
          />
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              onClick={capturePhoto}
              disabled={!videoReady}
              title={videoReady ? undefined : "Waiting for the camera…"}
              style={{ backgroundColor: "#2563eb", color: "white", border: "none", padding: "0.5rem 1rem", borderRadius: 4 }}
            >
              {videoReady ? "Capture" : "Starting camera…"}
            </button>
            <button onClick={closeCamera}>Cancel</button>
          </div>
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
            (() => {
              const typeBadge = (item: ReviewItem) => ({
                fontSize: "0.75rem",
                padding: "0.15rem 0.4rem",
                borderRadius: "4px",
                backgroundColor: item.itemType === "ingredient" ? "#1e3a2f" : "#3b1e2f",
                color: item.itemType === "ingredient" ? "#4ade80" : "#f9a8d4",
              });
              const derive = (item: ReviewItem) => {
                const addedNum = parseQty(item.addedQty);
                const isInvalid = Number.isNaN(addedNum);
                const isNew = item.existingQty === 0;
                const resultLabel = isInvalid
                  ? "—"
                  : isNew
                    ? `${addedNum}g (new)`
                    : `+${addedNum} → ${item.existingQty + addedNum}g`;
                return { addedNum, isInvalid, isNew, resultLabel };
              };
              const onQtyChange = (index: number) => (e: ChangeEvent<HTMLInputElement>) => {
                const v = e.target.value;
                if (v === "" || /^\d*\.?\d*$/.test(v)) {
                  updateReviewItem(index, "addedQty", v);
                  setConfirmError("");
                }
              };

              if (isMobile) {
                return (
                  <div style={{ marginBottom: "0.5rem" }}>
                    {reviewItems.map((item, index) => {
                      const { isInvalid, isNew, resultLabel } = derive(item);
                      return (
                        <div key={index} style={{ border: "1px solid #334155", borderRadius: 8, padding: "0.6rem 0.75rem", marginBottom: "0.5rem" }}>
                          <input
                            type="text"
                            value={item.name}
                            onChange={(e) => updateReviewItem(index, "name", e.target.value)}
                            aria-label={`Item ${index + 1} name`}
                            style={{ width: "100%", boxSizing: "border-box" }}
                          />
                          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", margin: "0.4rem 0" }}>
                            <span style={typeBadge(item)}>
                              {item.itemType === "ingredient" ? "ingredient" : "snack"}
                            </span>
                            <span style={{ fontSize: "0.85rem", color: isNew && !isInvalid ? "#4ade80" : "#94a3b8" }}>
                              {resultLabel}
                            </span>
                          </div>
                          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end" }}>
                            <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.8rem" }}>
                              Qty (g)
                              <input
                                type="text"
                                inputMode="decimal"
                                value={item.addedQty}
                                onChange={onQtyChange(index)}
                                style={{ width: "6rem", border: isInvalid ? "1px solid #ef4444" : undefined }}
                                aria-invalid={isInvalid}
                                aria-label={`Item ${index + 1} quantity`}
                              />
                            </label>
                            <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.8rem" }}>
                              Expires
                              <input
                                type="date"
                                value={item.expirationDate ?? ""}
                                onChange={(e) => updateReviewItem(index, "expirationDate", e.target.value || null)}
                                aria-label={`Item ${index + 1} expiration date`}
                              />
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.85rem" }}>
                              <input
                                type="checkbox"
                                checked={item.needToUse}
                                onChange={() => updateReviewItem(index, "needToUse", !item.needToUse)}
                                aria-label={`Item ${index + 1} need to use soon`}
                              />
                              use soon
                            </label>
                          </div>
                          <button onClick={() => removeReviewItem(index)} style={{ width: "100%", marginTop: "0.5rem" }}>
                            Remove
                          </button>
                        </div>
                      );
                    })}
                  </div>
                );
              }

              return (
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
                      const { isInvalid, isNew, resultLabel } = derive(item);
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
                            <span style={typeBadge(item)}>
                              {item.itemType === "ingredient" ? "ingredient" : "snack"}
                            </span>
                          </td>
                          <td>
                            <input
                              type="text"
                              inputMode="decimal"
                              value={item.addedQty}
                              onChange={onQtyChange(index)}
                              style={{ width: "80px", border: isInvalid ? "1px solid #ef4444" : undefined }}
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
              );
            })()
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
