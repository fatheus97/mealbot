import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../contexts/AuthContext.tsx";
import { useFridge, useUpdateFridge } from "../hooks/useServerState";
import type { StockItem } from "../types";
import { ReceiptScanner } from "./ReceiptScanner";

export function Fridge() {
  const { userId } = useAuth();

  const { data: serverFridge, isLoading, error: fetchError } = useFridge(userId);
  const updateFridgeMutation = useUpdateFridge();

  const [fridge, setFridge] = useState<StockItem[]>([]);
  const [notice, setNotice] = useState<string>("");
  const [expanded, setExpanded] = useState(true);
  const [sortKey, setSortKey] = useState<"name" | "quantity">("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const sortRef = useRef({ key: "name" as "name" | "quantity", dir: "asc" as "asc" | "desc" });

  const applySortToItems = useCallback((items: StockItem[], key: "name" | "quantity", dir: "asc" | "desc"): StockItem[] => {
    return [...items].sort((a, b) => {
      const cmp = key === "name"
        ? a.name.localeCompare(b.name)
        : a.quantity_grams - b.quantity_grams;
      return dir === "asc" ? cmp : -cmp;
    });
  }, []);

  useEffect(() => {
    if (serverFridge) {
      const copy: StockItem[] = JSON.parse(JSON.stringify(serverFridge));
      const { key, dir } = sortRef.current;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setFridge(applySortToItems(copy, key, dir));
    }
  }, [serverFridge, applySortToItems]);

  const addFridgeItem = () => {
    setFridge([
      ...fridge,
      { name: "", quantity_grams: 100, need_to_use: false }
    ]);
  };

  const removeFridgeItem = (index: number) => {
    const updated = [...fridge];
    updated.splice(index, 1);
    setFridge(updated);
  };

  const toggleNeedToUse = (index: number) => {
    const updated = [...fridge];
    updated[index].need_to_use = !updated[index].need_to_use;
    setFridge(updated);
  };

  const updateFridgeItem = <K extends keyof StockItem>(
    index: number,
    field: K,
    value: StockItem[K]
  ) => {
    const updated = [...fridge];
    updated[index] = { ...updated[index], [field]: value };
    setFridge(updated);
  };

  const toggleSort = (key: "name" | "quantity") => {
    const newDir = sortKey === key
      ? (sortDir === "asc" ? "desc" : "asc")
      : "asc";
    setSortKey(key);
    setSortDir(newDir);
    sortRef.current = { key, dir: newDir };
    setFridge((prev) => applySortToItems(prev, key, newDir));
  };

  const handleSaveFridge = async () => {
    if (!userId) return;

    const cleanedFridge = fridge.filter((item) => item.name.trim() !== "");

    try {
      await updateFridgeMutation.mutateAsync({ userId, items: cleanedFridge });

      setNotice("Fridge saved successfully!");
      setTimeout(() => setNotice(""), 3000);
    } catch (err) {
      if (err instanceof Error) {
        setNotice(`Failed to save: ${err.message}`);
      } else {
        setNotice("Failed to save: Unknown error occurred.");
      }
    }
  };

  if (!userId) {
    return (
      <section style={{ marginBottom: "2rem" }}>
        <h2>Fridge</h2>
        <p>Please log in to view and edit your fridge.</p>
      </section>
    );
  }

  return (
    <section style={{ marginBottom: "2rem" }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", userSelect: "none" }}
        onClick={() => setExpanded(!expanded)}
      >
        <span style={{ fontSize: "0.9rem", color: "#888" }}>{expanded ? "\u25BC" : "\u25B6"}</span>
        <h2 style={{ margin: 0 }}>Fridge</h2>
        {fridge.length > 0 && (
          <span style={{ fontSize: "0.85rem", color: "#888" }}>({fridge.length})</span>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: "1rem" }}>
          <ReceiptScanner currentFridge={fridge} />

          {isLoading && <p>Loading inventory...</p>}
          {fetchError && <p style={{ color: "red" }}>Error: {fetchError.message}</p>}

          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
                <th style={{ cursor: "pointer", userSelect: "none" }} onClick={() => toggleSort("name")}>
                  Ingredient{sortKey === "name" ? (sortDir === "asc" ? " ▲" : " ▼") : null}
                </th>
                <th style={{ cursor: "pointer", userSelect: "none" }} onClick={() => toggleSort("quantity")}>
                  Qty (g){sortKey === "quantity" ? (sortDir === "asc" ? " ▲" : " ▼") : null}
                </th>
                <th>Need to use?</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {fridge.map((item, index) => (
                <tr key={index} style={{ borderBottom: "1px solid #eee" }}>
                  <td>
                    <input
                      type="text"
                      value={item.name}
                      onChange={(e) => updateFridgeItem(index, "name", e.target.value)}
                      placeholder="e.g. Chicken breast"
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      value={item.quantity_grams}
                      onChange={(e) => updateFridgeItem(index, "quantity_grams", parseInt(e.target.value) || 0)}
                      style={{ width: "60px" }}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={item.need_to_use}
                      onChange={() => toggleNeedToUse(index)}
                    />
                  </td>
                  <td>
                    <button onClick={() => removeFridgeItem(index)}>Remove</button>
                  </td>
                </tr>
              ))}
              {fridge.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={4}>Fridge is empty.</td>
                </tr>
              )}
            </tbody>
          </table>

          <div style={{ marginTop: "0.5rem" }}>
            <button onClick={addFridgeItem}>Add ingredient</button>{" "}
            <button onClick={handleSaveFridge} disabled={updateFridgeMutation.isPending}>
              {updateFridgeMutation.isPending ? "Saving..." : "Save fridge"}
            </button>
            {notice && (
              <div style={{ marginTop: "0.5rem", color: updateFridgeMutation.isError ? "red" : "green" }}>
                {notice}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}