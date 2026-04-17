import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useAuth } from "../contexts/AuthContext.tsx";
import { useFridge, useUpdateFridge } from "../hooks/useServerState";
import type { StockItem } from "../types";
import { ReceiptScanner } from "./ReceiptScanner";
import { FridgeItemModal } from "./FridgeItemModal";
import type { FridgeItemValues } from "./FridgeItemModal";

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
      .map(({ _editId: _, ...rest }) => rest);
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

  const removeFridgeItem = (index: number) => {
    const updated = [...fridge];
    updated.splice(index, 1);
    setFridge(updated);
    refreshGroupOrder(updated, sortKey, sortDir);
    persistFridge(updated);
  };

  const removeGroup = (indices: number[]) => {
    const sorted = [...indices].sort((a, b) => b - a);
    const updated = [...fridge];
    for (const idx of sorted) updated.splice(idx, 1);
    setFridge(updated);
    refreshGroupOrder(updated, sortKey, sortDir);
    persistFridge(updated);
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
          <button onClick={() => removeFridgeItem(idx)}>Remove</button>
        </td>
      </tr>
    );
  };

  const renderMultiBatchGroup = (group: GroupedItem) => {
    const isExpanded = expandedGroups.has(group.key);
    const rows: React.ReactNode[] = [];

    // Summary row
    rows.push(
      <tr
        key={group.key}
        style={{
          borderBottom: isExpanded ? "none" : "1px solid #eee",
          backgroundColor: isExpanded ? "#1e293b" : "transparent",
          cursor: "pointer",
        }}
        onClick={() => toggleGroup(group.key)}
      >
        <td style={{ userSelect: "none", display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <span style={{ fontSize: "0.8rem", color: "#888" }}>
            {isExpanded ? "\u25BC" : "\u25B6"}
          </span>
          <span>{group.displayName}</span>
          <span style={{ fontSize: "0.8rem", color: "#64748b", whiteSpace: "nowrap" }}>
            ({group.batchCount} batches)
          </span>
        </td>
        <td style={{ color: "#94a3b8" }}>{Math.round(group.totalQuantity)}</td>
        <td style={{ fontSize: "0.85rem", color: "#94a3b8" }}>
          {formatDate(group.earliestExpiration)}
        </td>
        <td>{group.needToUse ? "Yes" : "No"}</td>
        <td>
          <button onClick={(e) => { e.stopPropagation(); removeGroup(group.flatIndices); }}>
            Remove all
          </button>
        </td>
      </tr>
    );

    // Sub-rows (when expanded), sorted by expiration date (earliest first, null last)
    if (isExpanded) {
      const sortedIndices = [...group.flatIndices].sort((a, b) => {
        const aDate = fridge[a].expiration_date ?? "";
        const bDate = fridge[b].expiration_date ?? "";
        if (!aDate && !bDate) return 0;
        if (!aDate) return 1;
        if (!bDate) return -1;
        return aDate.localeCompare(bDate);
      });
      sortedIndices.forEach((flatIdx, batchIdx) => {
        const item = fridge[flatIdx];
        rows.push(
          <tr
            key={`${group.key}_batch_${batchIdx}`}
            style={{
              borderBottom: batchIdx === sortedIndices.length - 1 ? "1px solid #eee" : "1px solid #334155",
              backgroundColor: "#0f172a",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <td style={{ paddingLeft: "2rem", color: "#94a3b8", fontSize: "0.9rem" }}>
              <span style={{ borderLeft: "2px solid #334155", paddingLeft: "0.5rem" }}>
                Batch {batchIdx + 1}
              </span>
            </td>
            <td>{Math.round(item.quantity_grams)}</td>
            <td style={{ fontSize: "0.85rem" }}>{formatDate(item.expiration_date)}</td>
            <td>{item.need_to_use ? "Yes" : "No"}</td>
            <td style={{ display: "flex", gap: "0.25rem" }}>
              <button onClick={() => openEditModal(flatIdx)}>Edit</button>
              <button onClick={() => removeFridgeItem(flatIdx)}>Remove</button>
            </td>
          </tr>
        );
      });
    }

    return rows;
  };

  return (
    <section style={{ marginBottom: "2rem" }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", userSelect: "none" }}
        onClick={() => setExpanded(!expanded)}
      >
        <span style={{ fontSize: "0.9rem", color: "#888" }}>{expanded ? "\u25BC" : "\u25B6"}</span>
        <h2 style={{ margin: 0 }}>Fridge</h2>
        {fridge.length > 0 && (
          <span style={{ fontSize: "0.85rem", color: "#888" }}>
            ({sortedGroups.length}{sortedGroups.length !== fridge.length ? ` / ${fridge.length} batches` : ""})
          </span>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: "1rem" }}>
          <ReceiptScanner currentFridge={fridge} />

          {isLoading && <p>Loading inventory...</p>}
          {fetchError && (
            <p style={{ color: fetchError instanceof TypeError ? "#888" : "red" }}>
              {fetchError instanceof TypeError ? "Connecting to server…" : `Error: ${fetchError.message}`}
            </p>
          )}

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
    </section>
  );
}
