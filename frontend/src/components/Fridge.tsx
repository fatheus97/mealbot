import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useAuth } from "../contexts/AuthContext.tsx";
import { useIsMobile } from "../hooks/useIsMobile";
import { usePrefersDark } from "../hooks/usePrefersDark";
import { useFridge, useUpdateFridge } from "../hooks/useServerState";
import type { StockItem } from "../types";
import { ReceiptScanner } from "./ReceiptScanner";
import { FridgeItemModal } from "./FridgeItemModal";
import type { FridgeItemValues } from "./FridgeItemModal";
import { ConfirmDialog } from "./ConfirmDialog";
import { MUTED_PAGE_TEXT, PAGE_TEXT } from "../constants/theme";

type PendingRemoval =
  | { kind: "item"; index: number; name: string; quantity: number }
  | { kind: "group"; indices: number[]; name: string; batchCount: number };

/** StockItem extended with a stable identity for edit-safe rendering. */
interface EditableStockItem extends StockItem {
  _editId: number;
}

interface GroupedItem {
  key: string;
  displayName: string;
  totalQuantity: number;
  earliestExpiration: string | null;
  needToUse: boolean;
  batchCount: number;
  flatIndices: number[];
}

type SortKey = "name" | "quantity" | "expires";

/**
 * Batch rows/cards pin a dark slate surface (#0f172a) in BOTH themes, so their
 * foregrounds are fixed rather than theme-following. Ratios on #0f172a:
 * body 14.48:1, muted 6.96:1, badge 5.61:1 — see contrast.test.ts.
 */
export const ON_DARK_SURFACE = "#0f172a";
export const ON_DARK_TEXT = "#e2e8f0";
export const ON_DARK_MUTED = "#94a3b8";
export const ON_DARK_ERROR = "#f87171";

/** Format ISO date string (YYYY-MM-DD) using the OS/browser locale, or return fallback. */
const localeDateFormatter = new Intl.DateTimeFormat(navigator.language, {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function formatDate(iso: string | null | undefined, fallback = "\u2014"): string {
  if (!iso) return fallback;
  // Parse as local date (not UTC) to avoid off-by-one from timezone shift
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  if (isNaN(date.getTime())) return iso;
  return localeDateFormatter.format(date);
}

export function Fridge() {
  const { userId } = useAuth();
  const isMobile = useIsMobile();
  const scheme = usePrefersDark() ? "dark" : "light";

  const { data: serverFridge, isLoading, error: fetchError } = useFridge(userId);
  const updateFridgeMutation = useUpdateFridge();

  const nextEditId = useRef(0);
  const assignId = (): number => nextEditId.current++;
  const [fridge, setFridge] = useState<EditableStockItem[]>([]);
  const [notice, setNotice] = useState("");
  const [expanded, setExpanded] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  // Stable group order — only changes on load, save, add, remove, and sort toggle
  const [groupOrder, setGroupOrder] = useState<string[]>([]);
  const [modalState, setModalState] = useState<{ mode: "add" | "edit"; editIndex: number | null } | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<PendingRemoval | null>(null);

  /** Build grouped items from the flat fridge array. */
  const buildGroups = useCallback((items: EditableStockItem[]): GroupedItem[] => {
    const groups = new Map<string, GroupedItem>();

    items.forEach((item, index) => {
      const trimmed = item.name.trim().toLowerCase();
      if (!trimmed) {
        // Blank items get a stable key from their _editId
        const stableKey = `__blank_${item._editId}`;
        groups.set(stableKey, {
          key: stableKey,
          displayName: "",
          totalQuantity: item.quantity_grams,
          earliestExpiration: item.expiration_date ?? null,
          needToUse: item.need_to_use,
          batchCount: 1,
          flatIndices: [index],
        });
        return;
      }

      const existing = groups.get(trimmed);
      if (existing) {
        // Merging into a multi-batch group: switch GroupedItem.key to name-based
        if (existing.batchCount === 1 && existing.key !== trimmed) {
          existing.key = trimmed;
        }
        existing.totalQuantity += item.quantity_grams;
        existing.flatIndices.push(index);
        existing.batchCount++;
        if (item.expiration_date) {
          if (!existing.earliestExpiration || item.expiration_date < existing.earliestExpiration) {
            existing.earliestExpiration = item.expiration_date;
            existing.needToUse = item.need_to_use;
          }
        }
        if (item.need_to_use) {
          existing.needToUse = true;
        }
      } else {
        // Single item: use stable _editId key so edits don't change position
        const stableKey = `__item_${item._editId}`;
        groups.set(trimmed, {
          key: stableKey,
          displayName: item.name,
          totalQuantity: item.quantity_grams,
          earliestExpiration: item.expiration_date ?? null,
          needToUse: item.need_to_use,
          batchCount: 1,
          flatIndices: [index],
        });
      }
    });

    return Array.from(groups.values());
  }, []);

  /** Sort groups by the current sort key/direction. */
  const sortGroups = useCallback((groups: GroupedItem[], key: SortKey, dir: "asc" | "desc"): string[] => {
    const sorted = [...groups];
    sorted.sort((a, b) => {
      let cmp: number;
      if (key === "name") {
        cmp = a.displayName.localeCompare(b.displayName);
      } else if (key === "quantity") {
        cmp = a.totalQuantity - b.totalQuantity;
      } else {
        const aDate = a.earliestExpiration ?? "";
        const bDate = b.earliestExpiration ?? "";
        if (!aDate && !bDate) cmp = 0;
        else if (!aDate) cmp = 1;
        else if (!bDate) cmp = -1;
        else cmp = aDate.localeCompare(bDate);
      }
      return dir === "asc" ? cmp : -cmp;
    });
    return sorted.map(g => g.key);
  }, []);

  /** Recompute and freeze group order from the current fridge state. */
  const refreshGroupOrder = useCallback((items: EditableStockItem[], key: SortKey, dir: "asc" | "desc") => {
    const groups = buildGroups(items);
    setGroupOrder(sortGroups(groups, key, dir));
  }, [buildGroups, sortGroups]);

  useEffect(() => {
    if (serverFridge) {
      const copy: EditableStockItem[] = serverFridge.map(item => ({
        ...JSON.parse(JSON.stringify(item)),
        _editId: assignId(),
      }));
      // Syncing fetched server data into editable local state with stable row
      // IDs — canonical external-sync effect, the rule's false-positive case.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setFridge(copy);
      refreshGroupOrder(copy, sortKey, sortDir);
    }
  // Only re-run when server data changes, not on sort changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverFridge, refreshGroupOrder]);

  // Live group data (totals, indices) — recomputes on edits, but ORDER is from groupOrder
  const groupedItems = useMemo(() => buildGroups(fridge), [fridge, buildGroups]);

  // Stable-ordered groups: use frozen order, look up live data
  const sortedGroups = useMemo(() => {
    const groupMap = new Map(groupedItems.map(g => [g.key, g]));
    const ordered: GroupedItem[] = [];
    // Render groups in the frozen order
    for (const key of groupOrder) {
      const g = groupMap.get(key);
      if (g) ordered.push(g);
    }
    // Append any new groups not yet in the order (e.g. newly added items)
    for (const g of groupedItems) {
      if (!groupOrder.includes(g.key)) ordered.push(g);
    }
    return ordered;
  }, [groupedItems, groupOrder]);

  /** Persist the given fridge items to the backend. */
  const persistFridge = (items: EditableStockItem[]) => {
    if (!userId) return;
    const cleaned: StockItem[] = items
      .filter((item) => item.name.trim() !== "")
      // Strip the client-only _editId before sending to the backend.
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      .map(({ _editId, ...rest }) => rest);
    updateFridgeMutation.mutate(
      { userId, items: cleaned },
      {
        onError: (err) => {
          const msg = err instanceof Error ? err.message : "Unknown error";
          setNotice(`Failed to save: ${msg}`);
          setTimeout(() => setNotice(""), 5000);
        },
      },
    );
  };

  const requestRemoveItem = (index: number) => {
    const item = fridge[index];
    if (!item) return;
    setPendingRemoval({
      kind: "item",
      index,
      name: item.name || "this item",
      quantity: item.quantity_grams,
    });
  };

  const requestRemoveGroup = (group: GroupedItem) => {
    setPendingRemoval({
      kind: "group",
      indices: group.flatIndices,
      name: group.displayName || "this group",
      batchCount: group.batchCount,
    });
  };

  const cancelRemoval = () => setPendingRemoval(null);

  const confirmRemoval = () => {
    if (!pendingRemoval) return;
    const indices =
      pendingRemoval.kind === "item" ? [pendingRemoval.index] : pendingRemoval.indices;
    // Sort descending so splices don't shift later indices.
    const sorted = [...indices].sort((a, b) => b - a);
    const updated = [...fridge];
    for (const idx of sorted) updated.splice(idx, 1);
    setFridge(updated);
    refreshGroupOrder(updated, sortKey, sortDir);
    persistFridge(updated);
    setPendingRemoval(null);
  };

  const openAddModal = () => setModalState({ mode: "add", editIndex: null });
  const openEditModal = (flatIndex: number) => setModalState({ mode: "edit", editIndex: flatIndex });

  const handleModalOk = (values: FridgeItemValues) => {
    let updated: EditableStockItem[];
    if (modalState?.mode === "add") {
      updated = [
        ...fridge,
        {
          name: values.name,
          quantity_grams: values.quantity_grams,
          need_to_use: values.need_to_use,
          expiration_date: values.expiration_date,
          _editId: assignId(),
        },
      ];
    } else if (modalState?.mode === "edit" && modalState.editIndex !== null) {
      updated = [...fridge];
      updated[modalState.editIndex] = {
        ...updated[modalState.editIndex],
        name: values.name,
        quantity_grams: values.quantity_grams,
        need_to_use: values.need_to_use,
        expiration_date: values.expiration_date,
      };
    } else {
      setModalState(null);
      return;
    }
    setFridge(updated);
    refreshGroupOrder(updated, sortKey, sortDir);
    persistFridge(updated);
    setModalState(null);
  };

  const handleModalCancel = () => setModalState(null);

  const toggleSort = (key: SortKey) => {
    const newDir = sortKey === key
      ? (sortDir === "asc" ? "desc" : "asc")
      : "asc";
    setSortKey(key);
    setSortDir(newDir);
    // Re-freeze order with current live data
    const groups = buildGroups(fridge);
    setGroupOrder(sortGroups(groups, key, newDir));
  };

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (!userId) {
    return (
      <section style={{ marginBottom: "2rem" }}>
        <h2>Fridge</h2>
        <p>Please log in to view and edit your fridge.</p>
      </section>
    );
  }

  // A group's batches ordered earliest-expiration first (null dates last).
  // Shared by the table (renderMultiBatchGroup) and card (renderMultiBatchCard)
  // renderers so their sub-row ordering can't drift apart.
  const sortedBatchIndices = (group: GroupedItem): number[] =>
    [...group.flatIndices].sort((a, b) => {
      const aDate = fridge[a].expiration_date ?? "";
      const bDate = fridge[b].expiration_date ?? "";
      if (!aDate && !bDate) return 0;
      if (!aDate) return 1;
      if (!bDate) return -1;
      return aDate.localeCompare(bDate);
    });

  const renderSingleRow = (group: GroupedItem) => {
    const idx = group.flatIndices[0];
    const item = fridge[idx];
    return (
      <tr key={item._editId} style={{ borderBottom: "1px solid #eee" }}>
        <td>{item.name}</td>
        <td>{Math.round(item.quantity_grams)}</td>
        <td style={{ fontSize: "0.85rem" }}>{formatDate(item.expiration_date)}</td>
        <td>{item.need_to_use ? "Yes" : "No"}</td>
        <td style={{ display: "flex", gap: "0.25rem" }}>
          <button onClick={() => openEditModal(idx)}>Edit</button>
          <button onClick={() => requestRemoveItem(idx)}>Remove</button>
        </td>
      </tr>
    );
  };

  const renderMultiBatchGroup = (group: GroupedItem) => {
    const isExpanded = expandedGroups.has(group.key);
    const rows: React.ReactNode[] = [];

    // Summary row
    const rowMuted = isExpanded ? ON_DARK_MUTED : PAGE_TEXT.muted[scheme];
    rows.push(
      <tr
        key={group.key}
        style={{
          borderBottom: isExpanded ? "none" : "1px solid #eee",
          // Expanded pins a dark slate surface, so it must pin a light colour
          // too — otherwise the row's text inherits the ADAPTIVE default and
          // goes dark-on-dark (#213547 on #1e293b = 1.6:1) in light mode.
          // Collapsed is transparent, so the adaptive default is right there.
          backgroundColor: isExpanded ? "#1e293b" : "transparent",
          color: isExpanded ? ON_DARK_TEXT : undefined,
          cursor: "pointer",
        }}
        onClick={() => toggleGroup(group.key)}
      >
        {/* This row is two-surfaced: expanded it pins #1e293b, collapsed it is
            transparent over the adaptive page background. A single fixed grey
            cannot clear AA on both (#94a3b8 is 5.71:1 on #1e293b but 2.56:1 on
            white), so the muted colour follows the surface the row is actually
            on. */}
        <td style={{ userSelect: "none", display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <span style={{ fontSize: "0.8rem", color: rowMuted }}>
            {isExpanded ? "\u25BC" : "\u25B6"}
          </span>
          <span>{group.displayName}</span>
          <span style={{ fontSize: "0.8rem", color: rowMuted, whiteSpace: "nowrap" }}>
            ({group.batchCount} batches)
          </span>
        </td>
        <td style={{ color: rowMuted }}>{Math.round(group.totalQuantity)}</td>
        <td style={{ fontSize: "0.85rem", color: rowMuted }}>
          {formatDate(group.earliestExpiration)}
        </td>
        <td>{group.needToUse ? "Yes" : "No"}</td>
        <td>
          <button onClick={(e) => { e.stopPropagation(); requestRemoveGroup(group); }}>
            Remove all
          </button>
        </td>
      </tr>
    );

    // Sub-rows (when expanded), sorted by expiration date (earliest first, null last)
    if (isExpanded) {
      const sortedIndices = sortedBatchIndices(group);
      sortedIndices.forEach((flatIdx, batchIdx) => {
        const item = fridge[flatIdx];
        rows.push(
          <tr
            key={`${group.key}_batch_${batchIdx}`}
            style={{
              borderBottom: batchIdx === sortedIndices.length - 1 ? "1px solid #eee" : "1px solid #334155",
              // Same as the summary row: a pinned dark surface needs a pinned
              // light colour, or the batch cells read #213547 on #0f172a
              // (1.42:1) in light mode. 14.48:1 both ways.
              backgroundColor: ON_DARK_SURFACE,
              color: ON_DARK_TEXT,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <td style={{ paddingLeft: "2rem", color: ON_DARK_MUTED, fontSize: "0.9rem" }}>
              <span style={{ borderLeft: "2px solid #334155", paddingLeft: "0.5rem" }}>
                Batch {batchIdx + 1}
              </span>
            </td>
            <td>{Math.round(item.quantity_grams)}</td>
            <td style={{ fontSize: "0.85rem" }}>{formatDate(item.expiration_date)}</td>
            <td>{item.need_to_use ? "Yes" : "No"}</td>
            <td style={{ display: "flex", gap: "0.25rem" }}>
              <button onClick={() => openEditModal(flatIdx)}>Edit</button>
              <button onClick={() => requestRemoveItem(flatIdx)}>Remove</button>
            </td>
          </tr>
        );
      });
    }

    return rows;
  };

  // --- Mobile card layout (the 5-col table is unusable at phone widths) ---
  const cardStyle: React.CSSProperties = {
    border: "1px solid #334155",
    borderRadius: 8,
    padding: "0.6rem 0.75rem",
    marginBottom: "0.5rem",
  };
  const cardHeaderRow: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "0.4rem",
    flexWrap: "wrap",
  };
  // These cards carry NO background of their own, so they sit on the adaptive
  // page background — but their palette was picked for a dark surface only.
  // Measured at 375px in light mode: the meta text was 2.56:1 and the badge
  // 1.9:1. Both now take the per-theme pair.
  const cardMeta: React.CSSProperties = {
    display: "flex",
    gap: "0.75rem",
    flexWrap: "wrap",
    fontSize: "0.85rem",
    color: PAGE_TEXT.muted[scheme],
    margin: "0.35rem 0",
  };
  const cardActions: React.CSSProperties = { display: "flex", gap: "0.4rem" };
  const cardActionBtn: React.CSSProperties = { flex: 1, padding: "0.4rem" };
  const useSoonBadge: React.CSSProperties = {
    fontSize: "0.7rem",
    color: PAGE_TEXT.error[scheme],
    border: `1px solid ${PAGE_TEXT.error[scheme]}`,
    borderRadius: 4,
    padding: "0.05rem 0.4rem",
  };
  // Batch cards pin #0f172a in BOTH themes, so anything inside them keeps a
  // fixed light foreground rather than following the OS scheme.
  const onDarkBadge: React.CSSProperties = { ...useSoonBadge, color: ON_DARK_ERROR, border: `1px solid ${ON_DARK_ERROR}` };

  const renderSingleCard = (group: GroupedItem) => {
    const idx = group.flatIndices[0];
    const item = fridge[idx];
    return (
      <div key={item._editId} style={cardStyle}>
        <div style={cardHeaderRow}>
          <strong>{item.name || "—"}</strong>
          {item.need_to_use && <span style={useSoonBadge}>use soon</span>}
        </div>
        <div style={cardMeta}>
          <span>{Math.round(item.quantity_grams)} g</span>
          <span>exp {formatDate(item.expiration_date)}</span>
        </div>
        <div style={cardActions}>
          <button style={cardActionBtn} onClick={() => openEditModal(idx)}>Edit</button>
          <button style={cardActionBtn} onClick={() => requestRemoveItem(idx)}>Remove</button>
        </div>
      </div>
    );
  };

  const renderMultiBatchCard = (group: GroupedItem) => {
    const isExpanded = expandedGroups.has(group.key);
    const sortedIndices = sortedBatchIndices(group);
    return (
      <div key={group.key} style={cardStyle}>
        <div style={{ ...cardHeaderRow, cursor: "pointer" }} onClick={() => toggleGroup(group.key)}>
          {/* The multi-batch CARD carries no background, so it is on the
              adaptive page background — #888 was 4.38:1 dark / 3.54:1 light. */}
          <span style={{ ...MUTED_PAGE_TEXT, fontSize: "0.8rem" }}>{isExpanded ? "▼" : "▶"}</span>
          <strong>{group.displayName}</strong>
          <span style={{ fontSize: "0.8rem", color: PAGE_TEXT.muted[scheme] }}>({group.batchCount} batches)</span>
          {group.needToUse && <span style={useSoonBadge}>use soon</span>}
        </div>
        <div style={cardMeta}>
          <span>{Math.round(group.totalQuantity)} g total</span>
          <span>earliest {formatDate(group.earliestExpiration)}</span>
        </div>
        <div style={cardActions}>
          <button style={cardActionBtn} onClick={() => requestRemoveGroup(group)}>Remove all</button>
        </div>
        {isExpanded && sortedIndices.map((flatIdx, batchIdx) => {
          const item = fridge[flatIdx];
          return (
            <div
              key={`${group.key}_batch_${batchIdx}`}
              style={{ ...cardStyle, marginTop: "0.5rem", marginBottom: 0, backgroundColor: ON_DARK_SURFACE, color: ON_DARK_TEXT }}
            >
              <div style={cardHeaderRow}>
                <span style={{ color: ON_DARK_MUTED }}>Batch {batchIdx + 1}</span>
                {item.need_to_use && <span style={onDarkBadge}>use soon</span>}
              </div>
              {/* This card pins #0f172a in BOTH themes, so it must NOT take the
                  theme-following `cardMeta` colour — #475569 on #0f172a is
                  1.7:1. Fixed surface, fixed foreground. */}
              <div style={{ ...cardMeta, color: ON_DARK_MUTED }}>
                <span>{Math.round(item.quantity_grams)} g</span>
                <span>exp {formatDate(item.expiration_date)}</span>
              </div>
              <div style={cardActions}>
                <button style={cardActionBtn} onClick={() => openEditModal(flatIdx)}>Edit</button>
                <button style={cardActionBtn} onClick={() => requestRemoveItem(flatIdx)}>Remove</button>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const mobileSortLabels: Record<SortKey, string> = {
    name: "Name",
    quantity: "Qty",
    expires: "Expires",
  };

  return (
    <section style={{ marginBottom: "2rem" }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", userSelect: "none" }}
        onClick={() => setExpanded(!expanded)}
      >
        {/* This header sits on the ADAPTIVE page background, so a fixed grey
            inverts with the theme: #888 measured 4.38:1 in dark and 3.54:1 in
            light \u2014 under AA in both. `inherit` + opacity dims whatever the
            adaptive default is instead. */}
        <span style={{ ...MUTED_PAGE_TEXT, fontSize: "0.9rem" }}>{expanded ? "\u25BC" : "\u25B6"}</span>
        <h2 style={{ margin: 0 }}>Fridge</h2>
        {fridge.length > 0 && (
          <span style={{ ...MUTED_PAGE_TEXT, fontSize: "0.85rem" }}>
            ({sortedGroups.length}{sortedGroups.length !== fridge.length ? ` / ${fridge.length} batches` : ""})
          </span>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: "1rem" }}>
          <ReceiptScanner currentFridge={fridge} />

          {isLoading && <p>Loading inventory...</p>}
          {/* Both branches sit on the adaptive page background. `red` is below
              AA in BOTH themes (4.00:1 light / 3.88:1 dark), so the error
              branch takes the per-theme pair from constants/theme. */}
          {fetchError && (
            <p
              style={
                fetchError instanceof TypeError
                  ? MUTED_PAGE_TEXT
                  : { color: PAGE_TEXT.error[scheme] }
              }
            >
              {fetchError instanceof TypeError ? "Connecting to server…" : `Error: ${fetchError.message}`}
            </p>
          )}

          {isMobile ? (
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  flexWrap: "wrap",
                  margin: "0.25rem 0 0.75rem",
                  fontSize: "0.85rem",
                }}
              >
                <span style={MUTED_PAGE_TEXT}>Sort:</span>
                {(["name", "quantity", "expires"] as SortKey[]).map((k) => (
                  <button
                    key={k}
                    onClick={() => toggleSort(k)}
                    style={{
                      padding: "0.25rem 0.6rem",
                      fontSize: "0.85rem",
                      minHeight: "unset",
                      borderColor: sortKey === k ? "#646cff" : undefined,
                    }}
                  >
                    {mobileSortLabels[k]}
                    {sortKey === k ? (sortDir === "asc" ? " \u25B2" : " \u25BC") : ""}
                  </button>
                ))}
              </div>
              {sortedGroups.map((group) =>
                group.batchCount === 1
                  ? renderSingleCard(group)
                  : renderMultiBatchCard(group)
              )}
              {fridge.length === 0 && !isLoading && <p>Fridge is empty.</p>}
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
                  <th style={{ cursor: "pointer", userSelect: "none" }} onClick={() => toggleSort("name")}>
                    Ingredient{sortKey === "name" ? (sortDir === "asc" ? " \u25B2" : " \u25BC") : null}
                  </th>
                  <th style={{ cursor: "pointer", userSelect: "none" }} onClick={() => toggleSort("quantity")}>
                    Qty (g){sortKey === "quantity" ? (sortDir === "asc" ? " \u25B2" : " \u25BC") : null}
                  </th>
                  <th style={{ cursor: "pointer", userSelect: "none" }} onClick={() => toggleSort("expires")}>
                    Expires{sortKey === "expires" ? (sortDir === "asc" ? " \u25B2" : " \u25BC") : null}
                  </th>
                  <th>Need to use?</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {sortedGroups.map((group) =>
                  group.batchCount === 1
                    ? renderSingleRow(group)
                    : renderMultiBatchGroup(group)
                )}
                {fridge.length === 0 && !isLoading && (
                  <tr>
                    <td colSpan={5}>Fridge is empty.</td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          <div style={{ marginTop: "0.5rem" }}>
            <button onClick={openAddModal}>Add ingredient</button>
            {notice && (
              <div style={{ marginTop: "0.5rem", color: "red" }}>
                {notice}
              </div>
            )}
          </div>
        </div>
      )}

      {modalState && (
        <FridgeItemModal
          mode={modalState.mode}
          initialValues={
            modalState.mode === "edit" && modalState.editIndex !== null
              ? {
                  name: fridge[modalState.editIndex].name,
                  quantity_grams: fridge[modalState.editIndex].quantity_grams,
                  expiration_date: fridge[modalState.editIndex].expiration_date ?? null,
                  need_to_use: fridge[modalState.editIndex].need_to_use,
                }
              : { name: "", quantity_grams: 100, expiration_date: null, need_to_use: false }
          }
          onOk={handleModalOk}
          onCancel={handleModalCancel}
        />
      )}

      {pendingRemoval && (
        <ConfirmDialog
          title={pendingRemoval.kind === "group" ? "Remove all batches?" : "Remove ingredient?"}
          message={
            pendingRemoval.kind === "group"
              ? `Remove all ${pendingRemoval.batchCount} batches of "${pendingRemoval.name}" from your fridge?`
              : `Remove "${pendingRemoval.name}" (${Math.round(pendingRemoval.quantity)} g) from your fridge?`
          }
          confirmLabel="Remove"
          loadingLabel="Removing…"
          onConfirm={confirmRemoval}
          onCancel={cancelRemoval}
        />
      )}
    </section>
  );
}
