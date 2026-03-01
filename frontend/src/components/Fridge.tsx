import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext.tsx";
import { useFridge, useUpdateFridge } from "../hooks/useServerState";
import type { StockItem } from "../types";

export function Fridge() {
  const { userId } = useAuth();

  const { data: serverFridge, isLoading, error: fetchError } = useFridge(userId);
  const updateFridgeMutation = useUpdateFridge();

  const [fridge, setFridge] = useState<StockItem[]>([]);
  const [notice, setNotice] = useState<string>("");

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

  const handleSaveFridge = () => {
    if (!userId) return;

    const cleanedFridge = fridge.filter((item) => item.name.trim() !== "");

    updateFridgeMutation.mutate(
      { userId, items: cleanedFridge },
      {
        onSuccess: () => {
          setNotice("Fridge saved successfully!");
          setTimeout(() => setNotice(""), 3000);
        },
        onError: (err: Error) => {
          setNotice(`Failed to save: ${err.message}`);
        }
      }
    );
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

      {isLoading && <p>Loading inventory...</p>}
      {fetchError && <p style={{ color: "red" }}>Error: {fetchError.message}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
            <th>Ingredient</th>
            <th>Qty (g)</th>
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
    </section>
  );
}