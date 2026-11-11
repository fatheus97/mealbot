import { useState, useRef, useEffect, useId } from "react";
import type { ChangeEvent } from "react";
import { useScanReceipt, useMergeFridge } from "../hooks/useServerState";
import { useAuth } from "../contexts/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import type { ScanSource, ScannedItemType, StockItem } from "../types";
import { InfoHint } from "./InfoHint";
import demoReceiptUrl from "../assets/demo-receipt.svg";
import { useI18n, type TranslationKey } from "../i18n";
import { isExpired } from "../utils/expiry";

type ScannerState = "idle" | "scanning" | "review" | "error" | "camera";

interface ReceiptScannerProps {
  currentFridge: StockItem[];
  /** Saves the list instead of merging it (Start fresh). Rejecting keeps the rows. */
  onSave?: (items: StockItem[], generationIds: number[]) => Promise<void>;
  /** The Confirm label for onSave, given the number of rows. */
  saveLabel?: (count: number) => string;
}

interface ReviewItem {
  name: string;
  addedQty: string;
  existingQty: number;
  needToUse: boolean;
  itemType?: ScannedItemType;
  expirationDate: string | null;
  // Set for an opened package from a food photo: its full size in grams. The
  // row asks how much is left, and addedQty starts empty until answered.
  packageGrams?: number;
  // Which scan of this review list the row came from (1, 2, ...), for the
  // "also in another scan" flag.
  scan: number;
}

const FLAG = { fontSize: "0.75rem", padding: "0.15rem 0.4rem", borderRadius: "4px" } as const;

// Quick answers to "how much is left?" for an opened package. "Almost nothing"
// is 5%: about a spoonful in a 500 g bag.
const LEFT_FRACTIONS: ReadonlyArray<readonly [number, string]> = [[0.25, "¼"], [0.5, "½"], [0.75, "¾"]];
const ALMOST_EMPTY_FRACTION = 0.05;

const parseQty = (s: string): number => {
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : NaN;
};

// Expiration dates are computed from shelf-life days at click time so the
// demo always shows dates relative to today — no stale "expired yesterday"
// rows for recruiters who open the demo weeks after the build.
const DEMO_SCAN_TEMPLATE: Array<
  Omit<ReviewItem, "expirationDate" | "name" | "scan"> & { nameKey: TranslationKey; shelfLifeDays: number }
> = [
  { nameKey: "receipt.demo.milk",     addedQty: "1000", existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 7 },
  { nameKey: "receipt.demo.eggs",     addedQty: "360",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 21 },
  { nameKey: "receipt.demo.bananas",  addedQty: "300",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 5 },
  { nameKey: "receipt.demo.butter",   addedQty: "250",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 30 },
  { nameKey: "receipt.demo.tomatoes", addedQty: "500",  existingQty: 0, needToUse: true,  itemType: "ingredient", shelfLifeDays: 4 },
  { nameKey: "receipt.demo.bread",    addedQty: "500",  existingQty: 0, needToUse: false, itemType: "ingredient", shelfLifeDays: 7 },
];

// Takes the translator rather than calling getI18n(): the names are resolved
// at CLICK time, so a user who switches language and then scans gets the demo
// in the language they are reading.
const buildDemoScanItems = (t: (key: TranslationKey) => string): ReviewItem[] => {
  const today = new Date();
  return DEMO_SCAN_TEMPLATE.map(({ shelfLifeDays, nameKey, ...item }) => {
    const exp = new Date(today);
    exp.setDate(exp.getDate() + shelfLifeDays);
    // YYYY-MM-DD in local time — matches the <input type="date"> format and
    // the backend's ISO date representation.
    const y = exp.getFullYear();
    const m = String(exp.getMonth() + 1).padStart(2, "0");
    const d = String(exp.getDate()).padStart(2, "0");
    return { ...item, name: t(nameKey), expirationDate: `${y}-${m}-${d}`, scan: 1 };
  });
};

export function ReceiptScanner({ currentFridge, onSave, saveLabel }: ReceiptScannerProps) {
  const { t } = useI18n();
  const { isDemo } = useAuth();
  const isMobile = useIsMobile();
  const [state, setState] = useState<ScannerState>("idle");
  // Receipt or a photo of the food itself. Switchable between scans; one review
  // list can mix both.
  const [source, setSource] = useState<ScanSource>("receipt");
  const sourceGroupName = useId();
  const isFoodPhoto = source === "food_photo";
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  // Scans in the review list on screen; 0 means there is no list. Once it is
  // above 0, a new scan appends and any failure keeps the rows (paid scans).
  const [scanCount, setScanCount] = useState(0);
  // machine_generation id of each of those scans, echoed back on merge so the
  // server can capture edits made in the review table. null for a scan whose
  // telemetry write was skipped; the demo path (no real /scan call) adds none.
  const [generationIds, setGenerationIds] = useState<(number | null)[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  // An add-another scan that found nothing says so here, under the list.
  const [scanInfo, setScanInfo] = useState("");
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
  // Guards the async canvas.toBlob() encode in capturePhoto the same way
  // openingRef guards getUserMedia — one capture at a time, and a cancel/unmount
  // during the encode drops the result instead of firing a scan.
  const capturingRef = useRef(false);
  // A ref mirror of `state` so the async openCamera()/capturePhoto() can read the
  // CURRENT state after their await (the closure's `state` is stale).
  const stateRef = useRef<ScannerState>(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const scanMutation = useScanReceipt();
  const mergeMutation = useMergeFridge();
  // onSave in flight: a second Confirm must not race it with a stale token.
  const [saving, setSaving] = useState(false);
  const confirming = saving || mergeMutation.isPending;

  // getUserMedia needs a secure context (HTTPS or localhost) and the API present.
  // Evaluated at render (not module load) so it reflects the live environment.
  const cameraSupported =
    typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

  // Release the camera (stop every track) — call on capture, cancel, and unmount
  // so a live camera indicator never lingers after the user is done.
  const stopCamera = () => {
    capturingRef.current = false;
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

  // With a review list on screen a failure shows inline and the rows stay: the
  // "error" state would hide them, and they are paid scans.
  const fail = (message: string) => {
    setErrorMessage(message);
    setState(scanCount > 0 ? "review" : "error");
  };

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
      // camera. "idle", "error" and "review" are openable (the button shows in
      // all three, so retry-after-denial and add-another must still work).
      const openableState =
        stateRef.current === "idle" || stateRef.current === "error" || stateRef.current === "review";
      if (!mountedRef.current || !openableState) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      setState("camera");
    } catch (err) {
      // Permission denied / no camera / insecure context — degrade to file upload
      // (the idle/error/review state still renders the file input).
      const name = err instanceof DOMException ? err.name : "";
      fail(
        name === "NotAllowedError"
          ? t("receipt.cameraDenied")
          : name === "NotFoundError"
            ? t("receipt.cameraNotFound")
            : t("receipt.cameraFailed"),
      );
    } finally {
      openingRef.current = false;
      setCameraOpening(false);
    }
  };

  const capturePhoto = () => {
    const video = videoRef.current;
    // Guard re-entry: a double-tap of Capture must not fire two encodes → two
    // scans + two telemetry rows for one photo.
    if (!video || capturingRef.current) return;
    capturingRef.current = true;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      stopCamera(); // resets capturingRef
      fail(t("receipt.captureFailed"));
      return;
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    // canvas → JPEG deliberately: gives us format control (sidesteps iOS HEIC,
    // which the backend rejects) AND compresses the phone photo before upload.
    canvas.toBlob(
      (blob) => {
        // If the user cancelled (Cancel → idle) or the component unmounted while
        // the encode ran, drop the result — don't fire a /scan they backed out
        // of. Still release the camera.
        if (!mountedRef.current || stateRef.current !== "camera") {
          stopCamera();
          return;
        }
        stopCamera(); // resets capturingRef
        if (!blob) {
          fail(t("receipt.captureFailed"));
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
    setState(scanCount > 0 ? "review" : "idle");
  };

  const handleScan = async (file: File) => {
    // With a list on screen this scan appends to it. The table stays up while
    // it runs (scanMutation.isPending, not the "scanning" state, which hides it).
    const adding = scanCount > 0;
    setState(adding ? "review" : "scanning");
    setErrorMessage("");
    setScanInfo("");

    try {
      const scanResponse = await scanMutation.mutateAsync({
        file,
        source,
        copy: { rateLimited: t("receipt.rateLimited"), fallback: t("receipt.scanFailed") },
      });
      const scannedItems = scanResponse.items;
      const id = scanResponse.generation_id;

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
          addedQty: scanned.opened ? "" : String(scanned.quantity_grams),
          existingQty: existing?.quantity_grams ?? 0,
          needToUse: existing?.need_to_use ?? false,
          itemType: scanned.item_type,
          expirationDate: expDate,
          packageGrams: scanned.opened ? scanned.quantity_grams : undefined,
          scan: scanCount + 1,
        };
      });

      setReviewItems((prev) => (adding ? [...prev, ...items] : items));
      setGenerationIds((prev) => [...(adding ? prev : []), id]);
      setScanCount(scanCount + 1);
      setState("review");
      if (adding && items.length === 0) {
        setScanInfo(source === "food_photo" ? t("receipt.noItemsFoodPhoto") : t("receipt.noItems"));
      }
    } catch (err) {
      fail(err instanceof Error ? err.message : t("receipt.scanFailed"));
    } finally {
      // Reset so selecting the same file again (e.g. after an error) re-triggers onChange.
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDemoScan = () => {
    setState("scanning");
    setGenerationIds([]); // demo skips the real /scan, so no generation
    setTimeout(() => {
      setReviewItems(buildDemoScanItems(t));
      setState("review");
    }, 1200);
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    void handleScan(file);
  };

  // The parent's save (Start fresh). `saving` spans the whole call, its reload
  // after a 409 included, so the next Confirm goes out with the new token.
  const saveVia = async (
    save: NonNullable<ReceiptScannerProps["onSave"]>,
    items: StockItem[],
    ids: number[],
  ) => {
    setSaving(true);
    try {
      await save(items, ids);
    } finally {
      setSaving(false);
    }
  };

  const handleConfirm = async () => {
    const invalidIdx = reviewItems.findIndex((item) => Number.isNaN(parseQty(item.addedQty)));
    if (invalidIdx !== -1) {
      setConfirmError(
        t("receipt.rowNeedsQty", {
          n: invalidIdx + 1,
          name: reviewItems[invalidIdx].name || t("receipt.unnamed"),
        }),
      );
      return;
    }

    const itemsToMerge: StockItem[] = reviewItems.map((item) => ({
      name: item.name,
      quantity_grams: parseQty(item.addedQty),
      need_to_use: item.needToUse,
      expiration_date: item.expirationDate,
    }));

    // The server compares the scans it can resolve with the WHOLE list, so one
    // unlinked scan would make an unedited save read as edited. Send no ids
    // then: telemetry skipped, never a false correction. Nor over the server's
    // limit of 20, where a prefix would be compared with the whole list.
    const linked = generationIds.filter((id): id is number => id !== null);
    const ids = linked.length === generationIds.length && linked.length <= 20 ? linked : [];
    try {
      if (onSave) {
        await saveVia(onSave, itemsToMerge, ids);
      } else {
        await mergeMutation.mutateAsync({
          items: itemsToMerge,
          generationIds: ids,
          copy: {
            rateLimited: t("receipt.rateLimited"),
            fallback: t("receipt.mergeFailed"),
            connectionLost: t("receipt.mergeConnectionLost"),
          },
        });
        setNotice(t("receipt.added"));
        setTimeout(() => setNotice(""), 3000);
      }
      clearList();
    } catch (err) {
      // Stay in review: the "error" state would hide the rows (paid scans).
      setConfirmError(err instanceof Error ? err.message : t("receipt.mergeFailed"));
    }
  };

  const clearList = () => {
    stopCamera(); // defensive: no path should leave a stream live here
    setState("idle");
    setReviewItems([]);
    setScanCount(0);
    setGenerationIds([]);
    setErrorMessage("");
    setScanInfo("");
    setConfirmError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // Functional updates: an edit made before a finished scan's rows render must
  // not overwrite the list with the one it was typed into.
  const updateReviewItem = <K extends keyof ReviewItem>(
    index: number,
    field: K,
    value: ReviewItem[K],
  ) => {
    setReviewItems((prev) => prev.map((item, i) => (i === index ? { ...item, [field]: value } : item)));
  };

  const removeReviewItem = (index: number) => {
    setReviewItems((prev) => prev.filter((_, i) => i !== index));
  };

  // Source, file and camera: the first scan in idle/error, "add another" in review.
  const busy = scanMutation.isPending || cameraOpening || confirming;
  const scanPickers = (
    <>
      <div
        role="radiogroup"
        aria-label={t("receipt.sourceLabel")}
        style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", width: "100%" }}
      >
        {([["receipt", "receipt.sourceReceipt"], ["food_photo", "receipt.sourceFoodPhoto"]] as const).map(
          ([value, labelKey]) => (
            <label key={value} style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
              <input
                type="radio"
                name={sourceGroupName}
                checked={source === value}
                onChange={() => setSource(value)}
                disabled={busy}
              />
              {t(labelKey)}
            </label>
          ),
        )}
        <InfoHint label={t("receipt.foodPhotoHintLabel")} text={t("receipt.foodPhotoHint")} />
      </div>
      <input
        ref={fileInputRef}
        type="file"
        // A food photo is never a PDF; the server rejects that pairing too.
        accept={isFoodPhoto ? "image/jpeg,image/png" : "image/jpeg,image/png,application/pdf,.pdf"}
        aria-label={isFoodPhoto ? t("receipt.selectFoodPhoto") : t("receipt.selectFile")}
        onChange={handleFileChange}
        disabled={busy}
      />
      {cameraSupported && (
        <button onClick={openCamera} disabled={busy}>
          {cameraOpening ? t("receipt.openingCamera") : t("receipt.takePhoto")}
        </button>
      )}
    </>
  );

  return (
    <div style={{ marginBottom: "1.5rem", padding: "1rem", backgroundColor: "#1e293b", borderRadius: "8px", color: "rgba(255, 255, 255, 0.87)" }}>
      <h3 style={{ marginTop: 0 }}>{t("receipt.heading")}</h3>

      {/* File input — always visible in idle/error states. Selecting a file auto-triggers the scan. */}
      {(state === "idle" || state === "error") && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
          {isDemo ? (
            <>
              <img
                src={demoReceiptUrl}
                alt={t("receipt.demoAlt")}
                style={{ height: 120, border: "1px solid #334155", borderRadius: 4 }}
              />
              <button onClick={handleDemoScan} disabled={scanMutation.isPending}>
                {t("receipt.scanDemo")}
              </button>
            </>
          ) : (
            <>
              {scanPickers}
              {onSave && (
                <button
                  onClick={() =>
                    void saveVia(onSave, [], []).catch((err: unknown) =>
                      fail(err instanceof Error ? err.message : t("receipt.mergeFailed")),
                    )
                  }
                  disabled={busy}
                >
                  {t("restock.emptyNow")}
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
            aria-label={t("receipt.cameraPreview")}
            onLoadedMetadata={() => setVideoReady(true)}
            style={{ width: "100%", maxWidth: 480, borderRadius: 8, background: "#000" }}
          />
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              onClick={capturePhoto}
              disabled={!videoReady}
              title={videoReady ? undefined : t("receipt.waitingForCamera")}
              style={{ backgroundColor: "#2563eb", color: "white", border: "none", padding: "0.5rem 1rem", borderRadius: 4 }}
            >
              {videoReady ? t("receipt.capture") : t("receipt.startingCamera")}
            </button>
            <button onClick={closeCamera}>{t("receipt.cancel")}</button>
          </div>
        </div>
      )}

      {/* Scanning state */}
      {state === "scanning" && (
        <p>{isFoodPhoto ? t("receipt.scanningFoodPhoto") : t("receipt.scanning")}</p>
      )}

      {/* Error state */}
      {state === "error" && (
        <p style={{ color: "#f87171", marginTop: "0.5rem" }}>{errorMessage}</p>
      )}

      {/* Review state */}
      {state === "review" && (
        <>
          {/* The expiry hint rides on the intro line, once, rather than on the
              "Expires" column: on mobile that label repeats on every card. */}
          <p style={{ color: "#94a3b8", marginBottom: "0.5rem" }}>
            {t("receipt.reviewIntro")}{" "}
            <InfoHint label={t("receipt.expiresHintLabel")} text={t("receipt.expiresHint")} />
          </p>
          {reviewItems.length === 0 ? (
            <p>{isFoodPhoto ? t("receipt.noItemsFoodPhoto") : t("receipt.noItems")}</p>
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
                    ? t("receipt.resultNew", { grams: addedNum })
                    : `+${addedNum} → ${item.existingQty + addedNum}g`;
                return { addedNum, isInvalid, isNew, resultLabel };
              };
              // The scans each name came from. Images are not normalized
              // against each other, so a name in two scans may be one food
              // seen twice (a receipt and a photo) or two real packs: flag it,
              // and let the person decide.
              const scansByName = new Map<string, Set<number>>();
              for (const row of reviewItems) {
                const key = row.name.trim().toLowerCase();
                if (key) scansByName.set(key, (scansByName.get(key) ?? new Set<number>()).add(row.scan));
              }
              const flags = (item: ReviewItem) => {
                const twin = (scansByName.get(item.name.trim().toLowerCase())?.size ?? 0) > 1;
                const past = isExpired({ expiration_date: item.expirationDate });
                if (!twin && !past) return null;
                return (
                  <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginTop: "0.3rem" }}>
                    {twin && (
                      <span style={{ ...FLAG, backgroundColor: "#3b2f1e", color: "#fbbf24" }}>
                        {t("receipt.alsoInOtherScan")}
                      </span>
                    )}
                    {past && (
                      <span style={{ ...FLAG, backgroundColor: "#3b1e1e", color: "#f87171" }}>
                        {t("receipt.pastDate")}
                      </span>
                    )}
                  </div>
                );
              };
              const setLeft = (index: number, grams: number) => {
                updateReviewItem(index, "addedQty", String(Math.max(1, Math.round(grams))));
                setConfirmError("");
              };
              const leftPrompt = (item: ReviewItem, index: number) => {
                const packageGrams = item.packageGrams;
                if (packageGrams === undefined) return null;
                const choices: ReadonlyArray<readonly [number, string]> = [
                  [ALMOST_EMPTY_FRACTION, t("receipt.leftAlmostEmpty")],
                  ...LEFT_FRACTIONS,
                ];
                return (
                  <div style={{ display: "flex", alignItems: "center", gap: "0.3rem", flexWrap: "wrap", fontSize: "0.8rem", color: "#fbbf24", marginTop: "0.3rem" }}>
                    <span>{t("receipt.openedAsk", { grams: packageGrams })}</span>
                    {choices.map(([fraction, label]) => (
                      <button
                        key={fraction}
                        type="button"
                        onClick={() => setLeft(index, packageGrams * fraction)}
                        aria-label={t("receipt.itemLeft", { n: index + 1, amount: label })}
                        style={{ padding: "0.1rem 0.45rem", fontSize: "0.8rem" }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                );
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
                            aria-label={t("receipt.itemName", { n: index + 1 })}
                            style={{ width: "100%", boxSizing: "border-box" }}
                          />
                          {flags(item)}
                          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", margin: "0.4rem 0" }}>
                            <span style={typeBadge(item)}>
                              {item.itemType === "ingredient" ? t("receipt.typeIngredient") : t("receipt.typeSnack")}
                            </span>
                            <span style={{ fontSize: "0.85rem", color: isNew && !isInvalid ? "#4ade80" : "#94a3b8" }}>
                              {resultLabel}
                            </span>
                          </div>
                          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end" }}>
                            <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.8rem" }}>
                              {t("receipt.qty")}
                              <input
                                type="text"
                                inputMode="decimal"
                                value={item.addedQty}
                                onChange={onQtyChange(index)}
                                style={{ width: "6rem", border: isInvalid ? "1px solid #ef4444" : undefined }}
                                aria-invalid={isInvalid}
                                aria-label={t("receipt.itemQty", { n: index + 1 })}
                              />
                            </label>
                            <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.8rem" }}>
                              {t("receipt.expires")}
                              <input
                                type="date"
                                value={item.expirationDate ?? ""}
                                onChange={(e) => updateReviewItem(index, "expirationDate", e.target.value || null)}
                                aria-label={t("receipt.itemExpiration", { n: index + 1 })}
                              />
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.85rem" }}>
                              <input
                                type="checkbox"
                                checked={item.needToUse}
                                onChange={() => updateReviewItem(index, "needToUse", !item.needToUse)}
                                aria-label={t("receipt.itemNeedToUse", { n: index + 1 })}
                              />
                              {t("receipt.useSoon")}
                            </label>
                          </div>
                          {leftPrompt(item, index)}
                          <button onClick={() => removeReviewItem(index)} style={{ width: "100%", marginTop: "0.5rem" }}>
                            {t("receipt.remove")}
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
                      <th>{t("receipt.colIngredient")}</th>
                      <th>{t("receipt.colType")}</th>
                      <th>{t("receipt.colAddedQty")}</th>
                      <th>{t("receipt.expires")}</th>
                      <th>{t("receipt.colResult")}</th>
                      <th>{t("receipt.colNeedToUse")}</th>
                      <th>{t("receipt.colAction")}</th>
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
                            {flags(item)}
                          </td>
                          <td>
                            <span style={typeBadge(item)}>
                              {item.itemType === "ingredient" ? t("receipt.typeIngredient") : t("receipt.typeSnack")}
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
                            {leftPrompt(item, index)}
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
                            <button onClick={() => removeReviewItem(index)}>{t("receipt.remove")}</button>
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
            <p role="alert" style={{ color: "#f87171", margin: "0.25rem 0 0.5rem" }}>{confirmError}</p>
          )}
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <button
              onClick={handleConfirm}
              // Not while a scan is adding rows (they would miss this save) or
              // the camera is being acquired (its stream would outlive the list).
              disabled={confirming || scanMutation.isPending || cameraOpening || reviewItems.length === 0}
              style={{ backgroundColor: "#2563eb", color: "white", border: "none", padding: "0.5rem 1rem", borderRadius: "4px", cursor: "pointer" }}
            >
              {saveLabel ? saveLabel(reviewItems.length) : mergeMutation.isPending ? t("receipt.adding") : t("receipt.add")}
            </button>
            {/* Not while a scan or camera is in flight: it would land after the
                list is gone and reopen a review of the discarded scan. */}
            <button onClick={clearList} disabled={scanMutation.isPending || cameraOpening}>
              {t("receipt.cancel")}
            </button>
          </div>
          {/* Below the buttons, so its status line toggling shifts nothing the
              person is about to click. The demo has a single scan only. */}
          {!isDemo && (
            <div style={{ marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid #334155" }}>
              <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>{t("receipt.addAnother")}</p>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
                {scanPickers}
              </div>
              {/* Always mounted, so screen readers announce what it says next. */}
              <p role="status" style={{ margin: "0.5rem 0 0" }}>
                {scanMutation.isPending
                  ? isFoodPhoto ? t("receipt.scanningFoodPhoto") : t("receipt.scanning")
                  : scanInfo}
              </p>
              {errorMessage && (
                <p role="alert" style={{ color: "#f87171", margin: "0.5rem 0 0" }}>{errorMessage}</p>
              )}
            </div>
          )}
        </>
      )}

      {notice && (
        <div style={{ marginTop: "0.5rem", color: "#4ade80" }}>{notice}</div>
      )}
    </div>
  );
}
