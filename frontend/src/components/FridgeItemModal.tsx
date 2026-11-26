import { useEffect, useState } from "react";
import { lookupKeepTime } from "../api";
import { useI18n } from "../i18n";
import type { DateKind, KeepTime } from "../types";
import { addDaysISO, todayISO } from "../utils/planDates";

export interface FridgeItemValues {
  name: string;
  quantity_grams: number;
  expiration_date: string | null;
  need_to_use: boolean;
  date_kind: DateKind | null;
}

// What the picker can say: a pack prints a use-by or a best-before date, and
// "" is "not from the pack".
type PackKind = "use_by" | "best_before" | "";
const packKindOf = (kind: DateKind | null): PackKind =>
  kind === "use_by" || kind === "best_before" ? kind : "";

// How long after the last keystroke a name is looked up.
const LOOKUP_DELAY_MS = 400;

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
  const { t, tn } = useI18n();
  const [name, setName] = useState(initialValues.name);
  const [quantity, setQuantity] = useState(String(initialValues.quantity_grams));
  const [expiration, setExpiration] = useState(initialValues.expiration_date ?? "");
  // The user has typed or cleared the date themselves: no suggestion after that.
  const [dateTouched, setDateTouched] = useState(false);
  const [needToUse, setNeedToUse] = useState(initialValues.need_to_use);
  const [packKind, setPackKind] = useState<PackKind>(packKindOf(initialValues.date_kind));
  const [error, setError] = useState("");
  const [quantityError, setQuantityError] = useState("");
  // The last lookup, with the name it answered, so a reply to an older name
  // can never stand for the current one.
  const [lookup, setLookup] = useState<{ query: string; keeps: KeepTime | null } | null>(null);

  // Manual add, pack without a date (docs/food-storage-design.md, slice 6b):
  // the USDA FoodKeeper time for the name, as today + its short end. It is a
  // suggestion, never state: picking Use by or Best before drops it (design
  // check 2, a table date never stands under a pack kind), and so does the
  // user touching the date.
  const query = mode === "add" && packKind === "" && !dateTouched ? name.trim() : "";
  const keeps = query && lookup?.query === query ? lookup.keeps : null;
  const suggested = keeps ? addDaysISO(todayISO(), keeps.low_days) : null;
  const shownDate = suggested ?? expiration;

  useEffect(() => {
    if (!query) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      lookupKeepTime(query, controller.signal)
        .then((found) => setLookup({ query, keeps: found }))
        // No suggestion is the safe failure: the user types the date as before.
        .catch(() => undefined);
    }, LOOKUP_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const keepsLine = (k: KeepTime): string => {
    if (k.low === k.high) {
      return k.unit === "Days" ? tn("storage.keepsDays", k.high) : tn("storage.keepsWeeks", k.high);
    }
    return k.unit === "Days"
      ? tn("storage.keepsDaysRange", k.high, { low: k.low })
      : tn("storage.keepsWeeksRange", k.high, { low: k.low });
  };

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
    const date = shownDate || null;
    // "No" keeps an estimate only while its date and name are untouched: a
    // date typed by hand is unknown unless the pack says which kind it is,
    // and an estimate made for another name says nothing about this one.
    const was = initialValues.date_kind;
    const untouched = date === initialValues.expiration_date && name.trim() === initialValues.name.trim();
    const unpacked = packKindOf(was) === "" && untouched ? was : null;
    onOk({
      name: name.trim(),
      quantity_grams: parsedQuantity,
      expiration_date: date,
      need_to_use: needToUse,
      date_kind: date === null ? null : packKind || (suggested !== null ? "estimated_table" : unpacked),
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
              value={shownDate}
              onChange={(e) => { setExpiration(e.target.value); setDateTouched(true); }}
              style={{ width: "160px" }}
            />
          </label>
          {/* The source line, on an add only. Its two lines are reserved, so
              the buttons do not jump when the lookup answers. Under a pack
              kind it says why the field is empty: the suggestion went with
              the pick (design check 2), and the pack's own date belongs there. */}
          {mode === "add" && (
            <span style={{ minHeight: "2.6em", marginTop: "-0.5rem", fontSize: "0.8rem", color: "#4b5563" }}>
              {keeps ? keepsLine(keeps) : packKind !== "" && !shownDate ? t("fridgeItem.typePackDate") : null}
            </span>
          )}

          {/* Always there on an add: "No" is what lets the table suggest the
              date above, and Use by or Best before takes the suggestion away. */}
          {(mode === "add" || shownDate) && (
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              {t("fridgeItem.dateKind")}
              <select
                value={packKind}
                onChange={(e) => setPackKind(e.target.value as PackKind)}
              >
                <option value="">{t("fridgeItem.dateKindNone")}</option>
                <option value="use_by">{t("fridgeItem.dateKindUseBy")}</option>
                <option value="best_before">{t("fridgeItem.dateKindBestBefore")}</option>
              </select>
            </label>
          )}

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
