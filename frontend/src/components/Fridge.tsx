import { useState, useEffect, useMemo } from "react";
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
  const [sortKey, setSortKey] = useState<"name" | "quantity" | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  useEffect(() => {
    if (serverFridge) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setFridge(JSON.parse(JSON.stringify(serverFridge)));
    }
  }, [serverFridge]);

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
    if (sortKey === key) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sortedFridge = useMemo(() => {
    const indexed = fridge.map((item, originalIndex) => ({ item, originalIndex }));
    if (sortKey === null) return indexed;

    return [...indexed].sort((a, b) => {
      let cmp: number;
      if (sortKey === "name") {
        cmp = a.item.name.localeCompare(b.item.name);
      } else {
        cmp = a.item.quantity_grams - b.item.quantity_grams;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [fridge, sortKey, sortDir]);

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
      <h2>Fridge</h2>

      <ReceiptScanner currentFridge={fridge} />

      {isLoading && <p>Loading inventory...</p>}
      {fetchError && <p style={{ color: "red" }}>Error: {fetchError.message}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
            <th style={{ cursor: "pointer", userSelect: "none" }} onClick={() => toggleSort("name")}>
              Ingredient{sortKey === "name" ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
            </th>
            <th style={{ cursor: "pointer", userSelect: "none" }} onClick={() => toggleSort("quantity")}>
              Qty (g){sortKey === "quantity" ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
            </th>
            <th>Need to use?</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {sortedFridge.map(({ item, originalIndex }) => (
            <tr key={originalIndex} style={{ borderBottom: "1px solid #eee" }}>
              <td>
                <input
                  type="text"
                  value={item.name}
                  onChange={(e) => updateFridgeItem(originalIndex, "name", e.target.value)}
                  placeholder="e.g. Chicken breast"
                />
              </td>
              <td>
                <input
                  type="number"
                  value={item.quantity_grams}
                  onChange={(e) => updateFridgeItem(originalIndex, "quantity_grams", parseInt(e.target.value) || 0)}
                  style={{ width: "60px" }}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={item.need_to_use}
                  onChange={() => toggleNeedToUse(originalIndex)}
                />
              </td>
              <td>
                <button onClick={() => removeFridgeItem(originalIndex)}>Remove</button>
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
    </section>
  );
}